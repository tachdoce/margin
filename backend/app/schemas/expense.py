import json
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.obligation import Obligation


class ExpenseCreate(BaseModel):
    obligation_type_id: int
    description: str
    is_monthly_recurring: bool
    due_day: int | None = None
    first_due_date: date | None = None
    currency_id: int
    amount: Decimal
    shift_weekends: bool | None = None


class ExpenseUpdate(BaseModel):
    obligation_type_id: int | None = None
    description: str | None = None
    is_monthly_recurring: bool | None = None
    due_day: int | None = None
    first_due_date: date | None = None
    currency_id: int | None = None
    amount: Decimal | None = None
    shift_weekends: bool | None = None
    is_closed: bool | None = None


class ExpenseOut(BaseModel):
    id: uuid.UUID
    obligation_type_id: int
    description: str | None
    is_monthly_recurring: bool
    due_day: int | None
    first_due_date: date | None
    currency_id: int
    amount: Decimal
    shift_weekends: bool
    is_closed: bool
    review_findings: list[str]
    is_ready: bool

    @classmethod
    def from_model(cls, o: Obligation) -> "ExpenseOut":
        return cls(
            id=o.id,
            obligation_type_id=o.obligation_type_id,
            description=o.description,
            is_monthly_recurring=o.is_monthly_recurring,
            due_day=o.due_day,
            first_due_date=o.first_due_date,
            currency_id=o.currency_id,
            amount=o.amount,
            shift_weekends=o.shift_weekends,
            is_closed=o.is_closed,
            review_findings=json.loads(o.review_findings),
            is_ready=o.is_ready,
        )
