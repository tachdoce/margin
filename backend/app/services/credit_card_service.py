import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem
from app.models.user import User


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
