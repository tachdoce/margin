import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.cash_flow_payment import CashFlowPayment


class PaymentCreate(BaseModel):
    amount: Decimal
    note: str | None = None
    plan_id: uuid.UUID | None = None
    planned_date: date | None = None


class PaymentUpdate(BaseModel):
    amount: Decimal | None = None
    note: str | None = None
    planned_date: date | None = None


class PaymentOut(BaseModel):
    id: uuid.UUID
    cash_flow_entry_id: uuid.UUID
    amount: Decimal
    note: str | None
    plan_id: uuid.UUID | None
    planned_date: date | None
    created_at: datetime

    @classmethod
    def from_model(cls, p: CashFlowPayment) -> "PaymentOut":
        return cls(
            id=p.id,
            cash_flow_entry_id=p.cash_flow_entry_id,
            amount=p.amount,
            note=p.note,
            plan_id=p.plan_id,
            planned_date=p.planned_date,
            created_at=p.created_at,
        )


class PaymentListItem(BaseModel):
    id: uuid.UUID
    cash_flow_entry_id: uuid.UUID
    amount: Decimal
    note: str | None
    is_planned: bool
    planned_date: date | None
    created_at: datetime

    @classmethod
    def from_model(cls, p: CashFlowPayment) -> "PaymentListItem":
        return cls(
            id=p.id,
            cash_flow_entry_id=p.cash_flow_entry_id,
            amount=p.amount,
            note=p.note,
            is_planned=p.plan_id is not None,
            planned_date=p.planned_date,
            created_at=p.created_at,
        )
