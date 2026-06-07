import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.income import Income


class IncomeCreate(BaseModel):
    income_type_id: int
    currency_id: int
    amount: Decimal
    description: str
    is_monthly_recurring: bool
    payment_day: int | None = None
    first_income_date: date | None = None
    total_months: int | None = None
    shift_weekends: bool | None = None


class IncomeUpdate(BaseModel):
    income_type_id: int | None = None
    currency_id: int | None = None
    amount: Decimal | None = None
    description: str | None = None
    is_monthly_recurring: bool | None = None
    payment_day: int | None = None
    first_income_date: date | None = None
    total_months: int | None = None
    shift_weekends: bool | None = None


class IncomeOut(BaseModel):
    id: uuid.UUID
    income_type_id: int
    currency_id: int
    amount: Decimal
    description: str
    is_monthly_recurring: bool
    payment_day: int | None
    first_income_date: date | None
    total_months: int | None
    shift_weekends: bool
    is_deleted: bool

    @classmethod
    def from_model(cls, income: Income) -> "IncomeOut":
        return cls(
            id=income.id,
            income_type_id=income.income_type_id,
            currency_id=income.currency_id,
            amount=income.amount,
            description=income.description,
            is_monthly_recurring=income.is_monthly_recurring,
            payment_day=income.payment_day,
            first_income_date=income.first_income_date,
            total_months=income.total_months,
            shift_weekends=income.shift_weekends,
            is_deleted=income.deleted_at is not None,
        )
