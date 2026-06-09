import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.credit_card import CreditCard
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_network import CreditCardNetwork
from app.models.credit_card_purchase import CreditCardPurchase
from app.models.currency import Currency
from app.models.institution import Institution
from app.models.staging_credit_card import StagingCreditCard
from app.models.staging_credit_card_item import StagingCreditCardItem
from app.models.user import User
from app.schemas.credit_card_statement import StagingItemUpdate, StagingMadreUpdate, StagingStatementCreate
from app.services.review.staging_credit_cards import review_staging_credit_card
from app.services.scoping import require_user_currency


def _resolve_institution(db: Session, country_code: str, name: str | None) -> int | None:
    if not name:
        return None
    return db.execute(
        select(Institution.id).where(
            Institution.name == name, Institution.country_code == country_code
        )
    ).scalars().first()


def _resolve_network(db: Session, country_code: str, name: str | None) -> int | None:
    if not name:
        return None
    return db.execute(
        select(CreditCardNetwork.id).where(
            CreditCardNetwork.name == name, CreditCardNetwork.country_code == country_code
        )
    ).scalars().first()


def _resolve_currency(db: Session, country_code: str, name: str | None) -> int | None:
    if not name:
        return None
    return db.execute(
        select(Currency.id).where(
            Currency.name == name,
            Currency.country_code == country_code,
            Currency.allowed_in_credit_card.is_(True),
        )
    ).scalars().first()


def _coalesce(next_v, this_v):
    return next_v if next_v is not None else this_v


def _inherited_types(db: Session, user_id, institution_id: int, card_network_id: int) -> dict[str, int]:
    """{description: item_type_id más reciente} de las compras de la tarjeta del usuario."""
    rows = db.execute(
        select(
            CreditCardPurchase.description,
            CreditCardPurchase.item_type_id,
        )
        .join(CreditCard, CreditCard.id == CreditCardPurchase.credit_card_id)
        .where(
            CreditCard.user_id == user_id,
            CreditCard.institution_id == institution_id,
            CreditCard.card_network_id == card_network_id,
        )
        .order_by(CreditCardPurchase.last_statement_closing_date.desc())
    ).all()
    result: dict[str, int] = {}
    for description, item_type_id in rows:
        if description not in result:  # la primera (más reciente) gana
            result[description] = item_type_id
    return result


def create_staging_statement(
    db: Session, user: User, payload: StagingStatementCreate
) -> tuple[StagingCreditCard, list[StagingCreditCardItem]]:
    cc = user.country_code
    gd, ps, rates = payload.general_data, payload.payment_summary, payload.annual_effective_rates

    institution_id = _resolve_institution(db, cc, gd.issuer)
    card_network_id = _resolve_network(db, cc, gd.card_network)
    rates_add_vat = None if rates.vat_excluded is None else (not rates.vat_excluded)

    # UPSERT de la madre por user_id (UNIQUE)
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id).with_for_update()
    ).scalar_one_or_none()
    if madre is None:
        madre = StagingCreditCard(user_id=user.id)
        db.add(madre)

    madre.institution_id = institution_id
    madre.card_network_id = card_network_id
    madre.closing_date = gd.closing_date
    madre.due_date = gd.due_date
    madre.current_limit = gd.current_limit
    madre.total_local = ps.total_local
    madre.total_usd = ps.total_usd
    madre.minimum_payment_local = ps.minimum_payment_local
    madre.minimum_payment_usd = ps.minimum_payment_usd
    madre.financing_rate_local = _coalesce(
        rates.financing_rate_local_next_month, rates.financing_rate_local_this_month
    )
    madre.overdue_rate_local = _coalesce(
        rates.overdue_rate_local_next_month, rates.overdue_rate_local_this_month
    )
    madre.financing_rate_usd = _coalesce(
        rates.financing_rate_usd_next_month, rates.financing_rate_usd_this_month
    )
    madre.overdue_rate_usd = _coalesce(
        rates.overdue_rate_usd_next_month, rates.overdue_rate_usd_this_month
    )
    madre.rates_add_vat = rates_add_vat
    # reset del ciclo de revisión
    madre.reviewed_at = None
    madre.review_findings = "[]"
    madre.user_acknowledged_at = None
    madre.is_ready = False
    db.flush()  # asegura madre.id

    # borrar y recrear ítems
    db.execute(
        delete(StagingCreditCardItem).where(StagingCreditCardItem.staging_credit_card_id == madre.id)
    )

    inherited: dict[str, int] = {}
    if institution_id is not None and card_network_id is not None:
        inherited = _inherited_types(db, user.id, institution_id, card_network_id)

    items: list[StagingCreditCardItem] = []
    for ch in payload.charges:
        currency_id = _resolve_currency(db, cc, ch.currency)
        item_type_id = inherited.get(ch.description) if ch.description is not None else None
        item = StagingCreditCardItem(
            staging_credit_card_id=madre.id,
            charge_date=ch.date,
            description=ch.description,
            amount=ch.amount,
            currency_id=currency_id,
            current_installment=ch.current_installment,
            total_installments=ch.total_installments,
            item_type_id=item_type_id,
        )
        db.add(item)
        items.append(item)
    db.flush()

    review_staging_credit_card(db, madre.id)
    db.commit()
    db.refresh(madre)
    return madre, items


def update_staging_madre(db: Session, user: User, payload: StagingMadreUpdate) -> StagingCreditCard:
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id).with_for_update()
    ).scalar_one_or_none()
    if madre is None:
        raise AppError(ErrorCode.not_found)

    required = (
        payload.institution_id, payload.card_network_id, payload.closing_date, payload.due_date,
        payload.current_limit, payload.total_local, payload.total_usd,
        payload.minimum_payment_local, payload.minimum_payment_usd, payload.rates_add_vat,
    )
    if any(v is None for v in required):
        raise AppError(ErrorCode.statement_incomplete)

    inst = db.get(Institution, payload.institution_id)
    if inst is None or inst.country_code != user.country_code:
        raise AppError(ErrorCode.institution_invalid, field="institution_id")
    net = db.get(CreditCardNetwork, payload.card_network_id)
    if net is None or net.country_code != user.country_code:
        raise AppError(ErrorCode.card_network_invalid, field="card_network_id")

    if payload.current_limit <= 0:
        raise AppError(ErrorCode.amount_invalid, field="current_limit")
    for f in ("total_local", "total_usd", "minimum_payment_local", "minimum_payment_usd"):
        if getattr(payload, f) < 0:
            raise AppError(ErrorCode.amount_invalid, field=f)

    prev_institution_id = madre.institution_id
    prev_card_network_id = madre.card_network_id

    madre.institution_id = payload.institution_id
    madre.card_network_id = payload.card_network_id
    madre.closing_date = payload.closing_date
    madre.due_date = payload.due_date
    madre.current_limit = payload.current_limit
    madre.total_local = payload.total_local
    madre.total_usd = payload.total_usd
    madre.minimum_payment_local = payload.minimum_payment_local
    madre.minimum_payment_usd = payload.minimum_payment_usd
    madre.financing_rate_local = payload.financing_rate_local
    madre.overdue_rate_local = payload.overdue_rate_local
    madre.financing_rate_usd = payload.financing_rate_usd
    madre.overdue_rate_usd = payload.overdue_rate_usd
    madre.rates_add_vat = payload.rates_add_vat
    db.flush()

    # herencia solo si recién ahora se resolvió la tarjeta (alguno estaba NULL antes; ambos no-NULL ahora)
    if prev_institution_id is None or prev_card_network_id is None:
        inherited = _inherited_types(db, user.id, payload.institution_id, payload.card_network_id)
        if inherited:
            null_items = db.execute(
                select(StagingCreditCardItem).where(
                    StagingCreditCardItem.staging_credit_card_id == madre.id,
                    StagingCreditCardItem.item_type_id.is_(None),
                )
            ).scalars().all()
            for it in null_items:
                if it.description in inherited:
                    it.item_type_id = inherited[it.description]
            db.flush()

    review_staging_credit_card(db, madre.id)
    db.commit()
    db.refresh(madre)
    return madre


def update_staging_item(
    db: Session, user: User, item_id: uuid.UUID, payload: StagingItemUpdate
) -> StagingCreditCardItem:
    item = db.execute(
        select(StagingCreditCardItem)
        .join(StagingCreditCard, StagingCreditCard.id == StagingCreditCardItem.staging_credit_card_id)
        .where(StagingCreditCardItem.id == item_id, StagingCreditCard.user_id == user.id)
        .with_for_update(of=StagingCreditCardItem)
    ).scalar_one_or_none()
    if item is None:
        raise AppError(ErrorCode.not_found)

    if (
        payload.charge_date is None
        or payload.description is None
        or payload.description.strip() == ""
        or payload.amount is None
        or payload.currency_id is None
        or payload.item_type_id is None
    ):
        raise AppError(ErrorCode.item_incomplete)

    currency = require_user_currency(db, user, payload.currency_id)  # 422 currency_not_available si país/inexistente
    if not currency.allowed_in_credit_card:
        raise AppError(ErrorCode.currency_not_available, field="currency_id")

    if payload.amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")

    if db.get(CreditCardItemType, payload.item_type_id) is None:
        raise AppError(ErrorCode.item_type_invalid, field="item_type_id")

    ci, ti = payload.current_installment, payload.total_installments
    if not (ci is None and ti is None):
        if ci is None or ti is None or ci < 1 or ti < 1 or ci > ti:
            raise AppError(ErrorCode.installments_invalid)

    item.charge_date = payload.charge_date
    item.description = payload.description
    item.amount = payload.amount
    item.currency_id = payload.currency_id
    item.item_type_id = payload.item_type_id
    item.current_installment = ci
    item.total_installments = ti
    db.commit()
    db.refresh(item)
    return item


def get_staging_statement(
    db: Session, user: User
) -> tuple[StagingCreditCard, list[StagingCreditCardItem]]:
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id)
    ).scalar_one_or_none()
    if madre is None:
        raise AppError(ErrorCode.not_found)
    items = db.execute(
        select(StagingCreditCardItem).where(StagingCreditCardItem.staging_credit_card_id == madre.id)
    ).scalars().all()
    return madre, list(items)


def delete_staging_statement(db: Session, user: User) -> None:
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id)
    ).scalar_one_or_none()
    if madre is None:
        raise AppError(ErrorCode.not_found)
    db.delete(madre)  # ítems por ON DELETE CASCADE
    db.commit()


def acknowledge_staging_statement(db: Session, user: User) -> StagingCreditCard:
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id).with_for_update()
    ).scalar_one_or_none()
    if madre is None:
        raise AppError(ErrorCode.not_found)
    if madre.review_findings == "[]":
        raise AppError(ErrorCode.statement_has_no_findings)
    # UPDATE puntual; updated_at se preserva (reconocer no es cambio de negocio).
    db.execute(
        update(StagingCreditCard)
        .where(StagingCreditCard.id == madre.id)
        .values(
            review_findings="[]",
            user_acknowledged_at=datetime.now(timezone.utc),
            is_ready=True,
            updated_at=madre.updated_at,
        )
    )
    db.commit()
    db.refresh(madre)
    return madre
