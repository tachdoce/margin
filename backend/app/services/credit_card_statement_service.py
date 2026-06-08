from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.credit_card import CreditCard
from app.models.credit_card_network import CreditCardNetwork
from app.models.credit_card_purchase import CreditCardPurchase
from app.models.currency import Currency
from app.models.institution import Institution
from app.models.staging_credit_card import StagingCreditCard
from app.models.staging_credit_card_item import StagingCreditCardItem
from app.models.user import User
from app.schemas.credit_card_statement import StagingStatementCreate
from app.services.review.staging_credit_cards import review_staging_credit_card


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
