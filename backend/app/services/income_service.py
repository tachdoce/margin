import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.income import Income
from app.models.income_type import IncomeType
from app.models.user import User
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.schemas.income import IncomeCreate, IncomeUpdate
from app.services.cash_flow.incomes import materialize_income
from app.services.scoping import require_user_currency

MIN_DESCRIPTION_LENGTH = 3


def _validate_income_type(db: Session, income_type_id: int | None) -> None:
    income_type = db.get(IncomeType, income_type_id) if income_type_id is not None else None
    if income_type is None or not income_type.visible:
        raise AppError(ErrorCode.income_type_invalid, field="income_type_id")


def _validate_amount(amount: Decimal | None) -> None:
    if amount is None or amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")


def _validate_description(description: str | None) -> str:
    cleaned = (description or "").strip()
    if len(cleaned) < MIN_DESCRIPTION_LENGTH:
        raise AppError(ErrorCode.description_invalid, field="description")
    return cleaned


def _validate_payment_day(payment_day: int | None) -> None:
    if payment_day is not None and not (1 <= payment_day <= 31):
        raise AppError(ErrorCode.payment_day_invalid, field="payment_day")


def _validate_form(
    is_monthly_recurring: bool,
    payment_day: int | None,
    first_income_date,
    total_months: int | None,
) -> None:
    """Modelo binario: recurrente infinito o duración fija. Valida el estado final."""
    if is_monthly_recurring:
        if payment_day is None:
            raise AppError(ErrorCode.recurring_income_requires_payment_day, field="payment_day")
        if first_income_date is not None or total_months is not None:
            raise AppError(ErrorCode.income_form_inconsistent)
    else:
        if first_income_date is None or total_months is None:
            raise AppError(ErrorCode.fixed_term_income_requires_dates)
        if total_months < 1:
            raise AppError(ErrorCode.total_months_invalid, field="total_months")
        if payment_day is not None:
            raise AppError(ErrorCode.income_form_inconsistent)


def create_income(db: Session, user: User, payload: IncomeCreate) -> Income:
    _validate_income_type(db, payload.income_type_id)
    require_user_currency(db, user, payload.currency_id)
    _validate_amount(payload.amount)
    description = _validate_description(payload.description)
    _validate_payment_day(payload.payment_day)
    _validate_form(
        payload.is_monthly_recurring, payload.payment_day, payload.first_income_date, payload.total_months
    )

    income = Income(
        user_id=user.id,
        income_type_id=payload.income_type_id,
        currency_id=payload.currency_id,
        amount=payload.amount,
        description=description,
        is_monthly_recurring=payload.is_monthly_recurring,
        payment_day=payload.payment_day,
        first_income_date=payload.first_income_date,
        total_months=payload.total_months,
        shift_weekends=payload.shift_weekends or False,
    )
    db.add(income)
    db.flush()
    materialize_income(db, income.id)
    db.commit()
    db.refresh(income)
    return income


def update_income(db: Session, user: User, income_id: uuid.UUID, payload: IncomeUpdate) -> Income:
    income = db.execute(
        select(Income).where(
            Income.id == income_id,
            Income.user_id == user.id,
            Income.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if income is None:
        raise AppError(ErrorCode.not_found)

    fields = payload.model_fields_set

    # Campos que no aceptan null explícito en PATCH (los nullable son payment_day,
    # first_income_date y total_months, que sí pueden setearse a NULL).
    for f in ("income_type_id", "currency_id", "amount", "description", "is_monthly_recurring", "shift_weekends"):
        if f in fields and getattr(payload, f) is None:
            raise AppError(ErrorCode.field_not_nullable, field=f)

    if "income_type_id" in fields:
        _validate_income_type(db, payload.income_type_id)
    if "currency_id" in fields:
        require_user_currency(db, user, payload.currency_id)
    if "amount" in fields:
        _validate_amount(payload.amount)
    new_description = None
    if "description" in fields:
        new_description = _validate_description(payload.description)
    if "payment_day" in fields:
        _validate_payment_day(payload.payment_day)

    final_recurring = payload.is_monthly_recurring if "is_monthly_recurring" in fields else income.is_monthly_recurring
    final_payment_day = payload.payment_day if "payment_day" in fields else income.payment_day
    final_first = payload.first_income_date if "first_income_date" in fields else income.first_income_date
    final_total = payload.total_months if "total_months" in fields else income.total_months
    _validate_form(final_recurring, final_payment_day, final_first, final_total)

    if "income_type_id" in fields:
        income.income_type_id = payload.income_type_id
    if "currency_id" in fields:
        income.currency_id = payload.currency_id
    if "amount" in fields:
        income.amount = payload.amount
    if "description" in fields:
        income.description = new_description
    if "is_monthly_recurring" in fields:
        income.is_monthly_recurring = payload.is_monthly_recurring
    if "payment_day" in fields:
        income.payment_day = payload.payment_day
    if "first_income_date" in fields:
        income.first_income_date = payload.first_income_date
    if "total_months" in fields:
        income.total_months = payload.total_months
    if "shift_weekends" in fields:
        income.shift_weekends = payload.shift_weekends

    db.flush()
    materialize_income(db, income.id)
    db.commit()
    db.refresh(income)
    return income


def list_incomes(db: Session, user: User) -> list[Income]:
    return list(
        db.execute(
            select(Income).where(Income.user_id == user.id).order_by(Income.created_at.desc())
        ).scalars()
    )


def delete_income(db: Session, user: User, income_id: uuid.UUID) -> None:
    """Borrado híbrido: hard-delete si el income no tiene pagos reales, soft-delete si los tiene.
    No invoca al motor; orquesta el borrado de las cash_flow_entries con SQL directo."""
    income = db.execute(
        select(Income).where(
            Income.id == income_id,
            Income.user_id == user.id,
            Income.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if income is None:
        raise AppError(ErrorCode.not_found)

    real_payments = db.execute(
        select(func.count())
        .select_from(CashFlowPayment)
        .join(CashFlowEntry, CashFlowPayment.cash_flow_entry_id == CashFlowEntry.id)
        .where(
            CashFlowEntry.source_type == "ingreso",
            CashFlowEntry.source_id == income.id,
            CashFlowPayment.plan_id.is_(None),
        )
    ).scalar_one()

    if real_payments == 0:
        # hard-delete total: todas las entries (sus planificados caen por cascade) + la fila
        db.execute(
            delete(CashFlowEntry).where(
                CashFlowEntry.source_type == "ingreso",
                CashFlowEntry.source_id == income.id,
            )
        )
        db.delete(income)
    else:
        # soft-delete: borrar solo las entries del income SIN pago real; las con pago sobreviven
        entries_with_real_payment = (
            select(CashFlowPayment.cash_flow_entry_id)
            .join(CashFlowEntry, CashFlowPayment.cash_flow_entry_id == CashFlowEntry.id)
            .where(
                CashFlowEntry.source_type == "ingreso",
                CashFlowEntry.source_id == income.id,
                CashFlowPayment.plan_id.is_(None),
            )
        )
        db.execute(
            delete(CashFlowEntry).where(
                CashFlowEntry.source_type == "ingreso",
                CashFlowEntry.source_id == income.id,
                CashFlowEntry.id.not_in(entries_with_real_payment),
            )
        )
        income.deleted_at = datetime.now(timezone.utc)

    db.commit()


def reactivate_income(db: Session, user: User, income_id: uuid.UUID) -> Income:
    income = db.execute(
        select(Income).where(
            Income.id == income_id,
            Income.user_id == user.id,
        )
    ).scalar_one_or_none()
    if income is None:
        raise AppError(ErrorCode.not_found)
    if income.deleted_at is None:
        raise AppError(ErrorCode.income_not_deleted)
    income.deleted_at = None
    db.flush()
    materialize_income(db, income.id)
    db.commit()
    db.refresh(income)
    return income
