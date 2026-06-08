import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.plan import Plan


class PlanCreate(BaseModel):
    name: str
    dial_amount: Decimal
    goal_kind: str | None = None
    goal_amount: Decimal | None = None
    select_on_create: bool = False


class PlanUpdate(BaseModel):
    name: str | None = None
    dial_amount: Decimal | None = None
    goal_kind: str | None = None
    goal_amount: Decimal | None = None


class PlanOut(BaseModel):
    id: uuid.UUID
    name: str
    is_default: bool
    is_engine_generated: bool
    selected_at: datetime
    dial_amount: Decimal
    dial_currency_id: int
    goal_kind: str | None
    goal_amount: Decimal | None
    goal_currency_id: int | None

    @classmethod
    def from_model(cls, plan: Plan) -> "PlanOut":
        return cls(
            id=plan.id,
            name=plan.name,
            is_default=plan.is_default,
            is_engine_generated=plan.is_engine_generated,
            selected_at=plan.selected_at,
            dial_amount=plan.dial_amount,
            dial_currency_id=plan.dial_currency_id,
            goal_kind=plan.goal_kind,
            goal_amount=plan.goal_amount,
            goal_currency_id=plan.goal_currency_id,
        )
