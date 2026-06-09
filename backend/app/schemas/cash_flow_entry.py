import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


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


class MonthEntryOut(TimelineEntryOut):
    event_date: date


class MonthOut(BaseModel):
    month: str
    total_income: Decimal
    total_expenses: Decimal
    balance: Decimal
    incomes: list[MonthEntryOut]
    expenses: list[MonthEntryOut]


class TimelineOut(BaseModel):
    months: list[MonthOut]
    open_debts: list[TimelineEntryOut]
