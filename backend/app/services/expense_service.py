import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.user import User
from app.schemas.expense import ExpenseCreate, ExpenseUpdate
from app.services.cash_flow.expenses import materialize_expense
from app.services.obligation_common import (
    validate_amount,
    validate_description,
    validate_due_day,
)
from app.services.review.obligations import review_obligation
from app.services.scoping import require_user_currency


def _require_gasto_type(db: Session, obligation_type_id: int | None) -> None:
    ot = db.get(ObligationType, obligation_type_id) if obligation_type_id is not None else None
    if ot is None or ot.obligation_kind != "gasto":
        raise AppError(ErrorCode.expense_type_invalid, field="obligation_type_id")


def _validate_form(is_monthly_recurring: bool, due_day, first_due_date) -> None:
    if is_monthly_recurring:
        if due_day is None:
            raise AppError(ErrorCode.expense_recurring_requires_due_day, field="due_day")
        if first_due_date is not None:
            raise AppError(ErrorCode.one_time_expense_inconsistent, field="first_due_date")
    else:
        if first_due_date is None or due_day is not None:
            raise AppError(ErrorCode.one_time_expense_inconsistent, field="first_due_date")


def _validate_first_due_date_future(first_due_date) -> None:
    if first_due_date is not None and first_due_date < date.today():
        raise AppError(ErrorCode.one_time_date_in_past, field="first_due_date")


def _gasto_query(user: User):
    return (
        select(Obligation)
        .join(ObligationType, ObligationType.id == Obligation.obligation_type_id)
        .where(Obligation.user_id == user.id, ObligationType.obligation_kind == "gasto")
    )


def create_expense(db: Session, user: User, payload: ExpenseCreate) -> Obligation:
    _require_gasto_type(db, payload.obligation_type_id)
    require_user_currency(db, user, payload.currency_id)
    description = validate_description(payload.description)
    validate_amount(payload.amount)
    validate_due_day(payload.due_day)
    _validate_form(payload.is_monthly_recurring, payload.due_day, payload.first_due_date)
    _validate_first_due_date_future(payload.first_due_date)

    obligation = Obligation(
        user_id=user.id,
        obligation_type_id=payload.obligation_type_id,
        description=description,
        is_monthly_recurring=payload.is_monthly_recurring,
        due_day=payload.due_day,
        first_due_date=payload.first_due_date,
        currency_id=payload.currency_id,
        amount=payload.amount,
        shift_weekends=payload.shift_weekends if payload.shift_weekends is not None else False,
        total_installments=None,
        financing_rate=None,
        overdue_rate=None,
        rates_add_vat=True,
        origin_obligation_id=None,
        institution_id=None,
        is_closed=False,
        reviewed_at=None,
        review_findings="[]",
        user_acknowledged_at=None,
        is_ready=False,
    )
    db.add(obligation)
    db.flush()
    review_obligation(db, obligation.id)
    materialize_expense(db, obligation.id)
    db.commit()
    db.refresh(obligation)
    return obligation


def list_expenses(db: Session, user: User) -> list[Obligation]:
    return list(
        db.execute(_gasto_query(user).order_by(Obligation.created_at.desc())).scalars()
    )


def update_expense(db: Session, user: User, obligation_id: uuid.UUID, payload: ExpenseUpdate) -> Obligation:
    obligation = db.execute(
        _gasto_query(user).where(Obligation.id == obligation_id)
    ).scalar_one_or_none()
    if obligation is None:
        raise AppError(ErrorCode.not_found)

    fields = payload.model_fields_set

    if "obligation_type_id" in fields:
        _require_gasto_type(db, payload.obligation_type_id)
    if "currency_id" in fields:
        require_user_currency(db, user, payload.currency_id)
    if "description" in fields:
        validate_description(payload.description)
    if "amount" in fields:
        validate_amount(payload.amount)
    if "due_day" in fields:
        validate_due_day(payload.due_day)
    for f in ("is_monthly_recurring", "shift_weekends", "is_closed"):
        if f in fields and getattr(payload, f) is None:
            raise AppError(ErrorCode.field_not_nullable, field=f)

    old_first_due_date = obligation.first_due_date
    for f in fields:
        value = getattr(payload, f)
        if f == "description":
            value = value.strip()
        setattr(obligation, f, value)

    _validate_form(obligation.is_monthly_recurring, obligation.due_day, obligation.first_due_date)
    if (
        "first_due_date" in fields
        and obligation.first_due_date is not None
        and obligation.first_due_date != old_first_due_date
    ):
        _validate_first_due_date_future(obligation.first_due_date)

    db.flush()
    review_obligation(db, obligation.id)
    materialize_expense(db, obligation.id)
    db.commit()
    db.refresh(obligation)
    return obligation
