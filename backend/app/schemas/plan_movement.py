import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.plan_movement import PlanMovement


class PlanMovementCreate(BaseModel):
    kind: str
    currency_id: int
    description: str | None = None
    principal_amount: Decimal | None = None
    start_date: date | None = None
    income_duration_months: int | None = None
    installment_amount: Decimal | None = None
    installment_start_date: date | None = None
    total_installments: int | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool | None = None


class TarjetazoCreate(BaseModel):
    installment_amount: Decimal
    total_installments: int
    credit_card_id: uuid.UUID
    currency_id: int


class PlanMovementUpdate(BaseModel):
    kind: str | None = None  # se ignora (el kind no es editable)
    currency_id: int | None = None
    description: str | None = None
    principal_amount: Decimal | None = None
    start_date: date | None = None
    income_duration_months: int | None = None
    installment_amount: Decimal | None = None
    installment_start_date: date | None = None
    total_installments: int | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool | None = None


class PlanMovementOut(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    kind: str
    currency_id: int
    description: str | None
    principal_amount: Decimal
    start_date: date
    income_duration_months: int | None
    installment_amount: Decimal | None
    installment_start_date: date | None
    total_installments: int | None
    financing_rate: Decimal | None
    overdue_rate: Decimal | None
    rates_add_vat: bool
    is_auto_generated: bool

    @classmethod
    def from_model(cls, m: PlanMovement) -> "PlanMovementOut":
        return cls(
            id=m.id,
            plan_id=m.plan_id,
            kind=m.kind,
            currency_id=m.currency_id,
            description=m.description,
            principal_amount=m.principal_amount,
            start_date=m.start_date,
            income_duration_months=m.income_duration_months,
            installment_amount=m.installment_amount,
            installment_start_date=m.installment_start_date,
            total_installments=m.total_installments,
            financing_rate=m.financing_rate,
            overdue_rate=m.overdue_rate,
            rates_add_vat=m.rates_add_vat,
            is_auto_generated=m.is_auto_generated,
        )
