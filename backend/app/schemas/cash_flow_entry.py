import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TimelineEntryOut(BaseModel):
    id: uuid.UUID
    amount: Decimal
    paid_real: Decimal
    planned_amount: Decimal
    currency_id: int
    source_type: str
    source_id: uuid.UUID
    description: str | None
    amount_converted: Decimal
    paid_real_converted: Decimal
    planned_amount_converted: Decimal
    financing_rate: Decimal
    overdue_rate: Decimal
    minimum_payment: Decimal | None


class MonthEntryOut(TimelineEntryOut):
    event_date: date


class MonthOut(BaseModel):
    month: str
    available: Decimal
    pending_income: Decimal
    pending_expenses: Decimal
    remaining_spending: Decimal
    balance: Decimal
    incomes: list[MonthEntryOut]
    expenses: list[MonthEntryOut]


class TimelineOut(BaseModel):
    months: list[MonthOut]
    open_debts: list[TimelineEntryOut]


class SourceEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_date: date
    amount: Decimal
    currency_id: int
    source_type: str


class EntryAmountUpdate(BaseModel):
    amount: Decimal
