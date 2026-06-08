import json
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.obligation import Obligation


class DebtCreate(BaseModel):
    obligation_type_id: int
    priority_level: int
    institution_id: int | None = None
    description: str
    due_day: int | None = None
    currency_id: int
    amount: Decimal
    total_installments: int | None = None
    first_due_date: date | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool | None = None
    shift_weekends: bool | None = None


class DebtUpdate(BaseModel):
    obligation_type_id: int | None = None
    priority_level: int | None = None
    institution_id: int | None = None
    description: str | None = None
    due_day: int | None = None
    currency_id: int | None = None
    amount: Decimal | None = None
    total_installments: int | None = None
    first_due_date: date | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool | None = None
    shift_weekends: bool | None = None
    is_closed: bool | None = None


class DebtOut(BaseModel):
    id: uuid.UUID
    obligation_type_id: int
    priority_level: int
    institution_id: int | None
    description: str | None
    is_monthly_recurring: bool
    due_day: int | None
    currency_id: int
    amount: Decimal
    total_installments: int | None
    first_due_date: date | None
    financing_rate: Decimal | None
    overdue_rate: Decimal | None
    rates_add_vat: bool
    origin_obligation_id: uuid.UUID | None
    shift_weekends: bool
    is_closed: bool
    review_findings: list[str]
    is_ready: bool

    @classmethod
    def from_model(cls, o: Obligation) -> "DebtOut":
        return cls(
            id=o.id,
            obligation_type_id=o.obligation_type_id,
            priority_level=o.priority_level,
            institution_id=o.institution_id,
            description=o.description,
            is_monthly_recurring=o.is_monthly_recurring,
            due_day=o.due_day,
            currency_id=o.currency_id,
            amount=o.amount,
            total_installments=o.total_installments,
            first_due_date=o.first_due_date,
            financing_rate=o.financing_rate,
            overdue_rate=o.overdue_rate,
            rates_add_vat=o.rates_add_vat,
            origin_obligation_id=o.origin_obligation_id,
            shift_weekends=o.shift_weekends,
            is_closed=o.is_closed,
            review_findings=json.loads(o.review_findings),
            is_ready=o.is_ready,
        )
