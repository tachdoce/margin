import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.credit_card import CreditCard
from app.models.credit_card_network import CreditCardNetwork
from app.models.credit_card_purchase import CreditCardPurchase
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem
from app.models.institution import Institution
from app.models.user import User
from app.schemas.credit_card import CreditCardUpdate
from app.services.cash_flow.credit_cards import materialize_credit_card
from app.services.obligation_common import validate_payment_config
from app.services.review.credit_cards import review_credit_card


def list_credit_cards(db: Session, user: User) -> list[CreditCard]:
    return list(
        db.execute(
            select(CreditCard)
            .where(CreditCard.user_id == user.id)
            .order_by(CreditCard.created_at)
        ).scalars()
    )


def _require_card(db: Session, user: User, card_id: uuid.UUID) -> CreditCard:
    """La tarjeta del usuario (sin filtrar deleted_at: el historial se ve aunque esté soft-deleted)."""
    card = db.execute(
        select(CreditCard).where(CreditCard.id == card_id, CreditCard.user_id == user.id)
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)
    return card


def list_statements(db: Session, user: User, card_id: uuid.UUID) -> list[CreditCardStatement]:
    _require_card(db, user, card_id)
    return list(
        db.execute(
            select(CreditCardStatement)
            .where(CreditCardStatement.credit_card_id == card_id)
            .order_by(CreditCardStatement.issue_year.desc(), CreditCardStatement.issue_month.desc())
        ).scalars()
    )


def list_statement_items(
    db: Session, user: User, card_id: uuid.UUID, statement_id: uuid.UUID
) -> list[CreditCardStatementItem]:
    _require_card(db, user, card_id)
    statement = db.execute(
        select(CreditCardStatement).where(
            CreditCardStatement.id == statement_id,
            CreditCardStatement.credit_card_id == card_id,
        )
    ).scalar_one_or_none()
    if statement is None:
        raise AppError(ErrorCode.not_found)
    return list(
        db.execute(
            select(CreditCardStatementItem)
            .where(CreditCardStatementItem.credit_card_statement_id == statement_id)
            .order_by(CreditCardStatementItem.charge_date)
        ).scalars()
    )


def update_credit_card(
    db: Session, user: User, card_id: uuid.UUID, payload: CreditCardUpdate
) -> CreditCard:
    card = db.execute(
        select(CreditCard).where(
            CreditCard.id == card_id,
            CreditCard.user_id == user.id,
            CreditCard.deleted_at.is_(None),
        ).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)

    if (
        payload.institution_id is None
        and payload.card_network_id is None
        and payload.closing_day is None
        and payload.due_day is None
        and payload.payment_rule is None
        and payload.priority is None
    ):
        raise AppError(ErrorCode.empty_patch)

    if payload.institution_id is not None:
        inst = db.get(Institution, payload.institution_id)
        if inst is None or inst.country_code != user.country_code:
            raise AppError(ErrorCode.institution_invalid, field="institution_id")
    if payload.card_network_id is not None:
        net = db.get(CreditCardNetwork, payload.card_network_id)
        if net is None or net.country_code != user.country_code:
            raise AppError(ErrorCode.card_network_invalid, field="card_network_id")
    if payload.closing_day is not None and not (1 <= payload.closing_day <= 31):
        raise AppError(ErrorCode.closing_day_invalid, field="closing_day")
    if payload.due_day is not None and not (1 <= payload.due_day <= 31):
        raise AppError(ErrorCode.due_day_invalid, field="due_day")

    # unicidad: combinación final contra otra vigente del usuario
    new_inst = payload.institution_id if payload.institution_id is not None else card.institution_id
    new_net = payload.card_network_id if payload.card_network_id is not None else card.card_network_id
    if new_inst != card.institution_id or new_net != card.card_network_id:
        clash = db.execute(
            select(CreditCard.id).where(
                CreditCard.user_id == user.id,
                CreditCard.institution_id == new_inst,
                CreditCard.card_network_id == new_net,
                CreditCard.deleted_at.is_(None),
                CreditCard.id != card.id,
            )
        ).first()
        if clash is not None:
            raise AppError(ErrorCode.card_already_exists)

    if payload.institution_id is not None:
        card.institution_id = payload.institution_id
    if payload.card_network_id is not None:
        card.card_network_id = payload.card_network_id
    if payload.closing_day is not None:
        card.closing_day = payload.closing_day
    if payload.due_day is not None:
        card.due_day = payload.due_day
    if payload.payment_rule is not None or payload.priority is not None:
        rule = payload.payment_rule if payload.payment_rule is not None else card.payment_rule
        pri = payload.priority if payload.priority is not None else card.priority
        validate_payment_config("deuda", payment_rule=rule, priority=pri,
                                monthly_paydown_amount=None, priority_open_debt=None)
        card.payment_rule = rule
        card.priority = pri
    db.flush()

    review_credit_card(db, card.id)
    materialize_credit_card(db, card.id)
    db.commit()
    db.refresh(card)
    return card


def acknowledge_credit_card(db: Session, user: User, card_id: uuid.UUID) -> CreditCard:
    card = db.execute(
        select(CreditCard).where(
            CreditCard.id == card_id,
            CreditCard.user_id == user.id,
            CreditCard.deleted_at.is_(None),
        ).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)
    if card.review_findings == "[]":
        raise AppError(ErrorCode.card_has_no_findings)

    # updated_at: bump si era nueva (created_at == updated_at) para que deje de serlo; si no, preservar.
    new_updated_at = (
        datetime.now(timezone.utc) if card.created_at == card.updated_at else card.updated_at
    )
    db.execute(
        update(CreditCard)
        .where(CreditCard.id == card.id)
        .values(
            review_findings="[]",
            user_acknowledged_at=datetime.now(timezone.utc),
            is_ready=True,
            updated_at=new_updated_at,
        )
    )
    materialize_credit_card(db, card.id)
    db.commit()
    db.refresh(card)
    return card


def delete_credit_card(db: Session, user: User, card_id: uuid.UUID) -> None:
    card = db.execute(
        select(CreditCard).where(
            CreditCard.id == card_id,
            CreditCard.user_id == user.id,
            CreditCard.deleted_at.is_(None),
        ).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)

    real_payments = db.execute(
        select(func.count())
        .select_from(CashFlowPayment)
        .join(CashFlowEntry, CashFlowPayment.cash_flow_entry_id == CashFlowEntry.id)
        .where(
            CashFlowEntry.source_type == "tarjeta_credito",
            CashFlowEntry.source_id == card.id,
            CashFlowPayment.plan_id.is_(None),
        )
    ).scalar_one()

    if real_payments == 0:
        # hard-delete total (orden por las FKs RESTRICT de statements/purchases hacia credit_cards)
        db.execute(
            delete(CashFlowEntry)
            .where(CashFlowEntry.source_type == "tarjeta_credito", CashFlowEntry.source_id == card.id)
            .execution_options(synchronize_session=False)
        )
        db.execute(
            delete(CreditCardPurchase)
            .where(CreditCardPurchase.credit_card_id == card.id)
            .execution_options(synchronize_session=False)
        )
        db.execute(
            delete(CreditCardStatement)
            .where(CreditCardStatement.credit_card_id == card.id)
            .execution_options(synchronize_session=False)
        )
        db.delete(card)
    else:
        # soft-delete: borrar solo las entries sin pago real; la tarjeta y la historia sobreviven
        paid_entry_ids = (
            select(CashFlowPayment.cash_flow_entry_id)
            .join(CashFlowEntry, CashFlowPayment.cash_flow_entry_id == CashFlowEntry.id)
            .where(
                CashFlowEntry.source_type == "tarjeta_credito",
                CashFlowEntry.source_id == card.id,
                CashFlowPayment.plan_id.is_(None),
            )
        )
        db.execute(
            delete(CashFlowEntry)
            .where(
                CashFlowEntry.source_type == "tarjeta_credito",
                CashFlowEntry.source_id == card.id,
                CashFlowEntry.id.not_in(paid_entry_ids),
            )
            .execution_options(synchronize_session=False)
        )
        card.deleted_at = datetime.now(timezone.utc)

    db.commit()


def delete_last_statement(db: Session, user: User, card_id: uuid.UUID) -> None:
    card = db.execute(
        select(CreditCard).where(
            CreditCard.id == card_id, CreditCard.user_id == user.id
        ).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)

    statement = db.execute(
        select(CreditCardStatement)
        .where(CreditCardStatement.credit_card_id == card.id)
        .order_by(CreditCardStatement.issue_year.desc(), CreditCardStatement.issue_month.desc())
        .limit(1)
    ).scalar_one_or_none()
    if statement is None:
        raise AppError(ErrorCode.not_found)

    real_payments = db.execute(
        select(func.count())
        .select_from(CashFlowPayment)
        .join(CashFlowEntry, CashFlowPayment.cash_flow_entry_id == CashFlowEntry.id)
        .where(
            CashFlowEntry.source_type == "tarjeta_credito",
            CashFlowEntry.source_id == card.id,
            CashFlowEntry.issue_year == statement.issue_year,
            CashFlowEntry.issue_month == statement.issue_month,
            CashFlowPayment.plan_id.is_(None),
        )
    ).scalar_one()
    if real_payments > 0:
        raise AppError(ErrorCode.statement_has_payments)

    db.delete(statement)  # items por ON DELETE CASCADE; purchases NO se tocan
    db.flush()
    materialize_credit_card(db, card.id)  # reproyecta desde el nuevo último
    db.commit()


def reactivate_credit_card(db: Session, user: User, card_id: uuid.UUID) -> CreditCard:
    card = db.execute(
        select(CreditCard).where(
            CreditCard.id == card_id, CreditCard.user_id == user.id
        ).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)
    if card.deleted_at is None:
        raise AppError(ErrorCode.card_not_deleted)

    clash = db.execute(
        select(CreditCard.id).where(
            CreditCard.user_id == user.id,
            CreditCard.institution_id == card.institution_id,
            CreditCard.card_network_id == card.card_network_id,
            CreditCard.deleted_at.is_(None),
            CreditCard.id != card.id,
        )
    ).first()
    if clash is not None:
        raise AppError(ErrorCode.card_already_exists)

    card.deleted_at = None
    db.flush()
    review_credit_card(db, card.id)
    materialize_credit_card(db, card.id)
    db.commit()
    db.refresh(card)
    return card
