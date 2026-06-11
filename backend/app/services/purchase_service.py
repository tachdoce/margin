import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.credit_card import CreditCard
from app.models.purchase import Purchase
from app.models.purchase_category import PurchaseCategory
from app.models.user import User
from app.schemas.purchase import PurchaseCreate, PurchaseUpdate
from app.services.cash_flow.credit_cards import materialize_credit_card
from app.services.scoping import require_holdable_currency

_EDITABLE = (
    "credit_card_id", "category_id", "description", "purchase_date",
    "amount", "currency_id", "total_installments",
)
_NOT_NULLABLE = ("purchase_date", "amount", "currency_id")


def _clean_description(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _validate_amount(amount) -> None:
    if amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")


def _validate_credit_card(db: Session, user: User, credit_card_id: uuid.UUID | None) -> None:
    if credit_card_id is None:
        return
    card = db.get(CreditCard, credit_card_id)
    if card is None or card.user_id != user.id or card.deleted_at is not None:
        raise AppError(ErrorCode.credit_card_invalid, field="credit_card_id")


def _validate_category(db: Session, category_id: int | None) -> None:
    if category_id is None:
        return
    if db.get(PurchaseCategory, category_id) is None:
        raise AppError(ErrorCode.purchase_category_invalid, field="category_id")


def _validate_installments(total_installments: int | None, credit_card_id: uuid.UUID | None) -> None:
    if total_installments is None:
        return
    if total_installments < 1:
        raise AppError(ErrorCode.installments_invalid, field="total_installments")
    if total_installments > 1 and credit_card_id is None:
        raise AppError(ErrorCode.installments_invalid, field="total_installments")


def create_purchase(db: Session, user: User, payload: PurchaseCreate) -> Purchase:
    require_holdable_currency(db, user, payload.currency_id)
    _validate_amount(payload.amount)
    _validate_credit_card(db, user, payload.credit_card_id)
    _validate_category(db, payload.category_id)
    _validate_installments(payload.total_installments, payload.credit_card_id)
    p = Purchase(
        user_id=user.id,
        credit_card_id=payload.credit_card_id,
        category_id=payload.category_id,
        total_installments=payload.total_installments,
        description=_clean_description(payload.description),
        purchase_date=payload.purchase_date,
        amount=payload.amount,
        currency_id=payload.currency_id,
    )
    db.add(p)
    db.flush()
    if p.credit_card_id is not None:
        materialize_credit_card(db, p.credit_card_id)
    db.commit()
    db.refresh(p)
    return p


def list_purchases(db: Session, user: User) -> list[Purchase]:
    return list(
        db.execute(
            select(Purchase)
            .where(Purchase.user_id == user.id)
            .order_by(Purchase.purchase_date.desc(), Purchase.created_at.desc())
        ).scalars()
    )


def _require_purchase(db: Session, user: User, purchase_id: uuid.UUID) -> Purchase:
    p = db.get(Purchase, purchase_id)
    if p is None or p.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    return p


def update_purchase(db: Session, user: User, purchase_id: uuid.UUID, payload: PurchaseUpdate) -> Purchase:
    p = _require_purchase(db, user, purchase_id)
    old_card_id = p.credit_card_id
    fields = payload.model_fields_set
    if not fields & set(_EDITABLE):
        raise AppError(ErrorCode.empty_patch)
    for name in _NOT_NULLABLE:
        if name in fields and getattr(payload, name) is None:
            raise AppError(ErrorCode.field_not_nullable, field=name)

    def final(name):
        return getattr(payload, name) if name in fields else getattr(p, name)

    require_holdable_currency(db, user, final("currency_id"))
    _validate_amount(final("amount"))
    _validate_credit_card(db, user, final("credit_card_id"))
    _validate_category(db, final("category_id"))
    _validate_installments(final("total_installments"), final("credit_card_id"))
    for name in fields & set(_EDITABLE):
        value = getattr(payload, name)
        if name == "description":
            value = _clean_description(value)
        setattr(p, name, value)
    db.flush()
    for card_id in {old_card_id, p.credit_card_id} - {None}:
        materialize_credit_card(db, card_id)
    db.commit()
    db.refresh(p)
    return p


def delete_purchase(db: Session, user: User, purchase_id: uuid.UUID) -> None:
    p = _require_purchase(db, user, purchase_id)
    card_id = p.credit_card_id
    db.delete(p)
    db.flush()
    if card_id is not None:
        materialize_credit_card(db, card_id)
    db.commit()
