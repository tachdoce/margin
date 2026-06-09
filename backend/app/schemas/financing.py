import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.financing import Financing


class FinancingCreate(BaseModel):
    currency_id: int
    description: str
    principal_amount: Decimal
    usage_preference: str
    start_date: date | None = None
    installment_start_date: date | None = None
    installment_amount: Decimal | None = None
    total_installments: int | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool = True


class FinancingUpdate(BaseModel):
    currency_id: int | None = None
    description: str | None = None
    principal_amount: Decimal | None = None
    usage_preference: str | None = None
    start_date: date | None = None
    installment_start_date: date | None = None
    installment_amount: Decimal | None = None
    total_installments: int | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool | None = None


class FinancingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    currency_id: int
    description: str
    principal_amount: Decimal
    usage_preference: str
    start_date: date | None
    installment_start_date: date | None
    installment_amount: Decimal | None
    total_installments: int | None
    financing_rate: Decimal | None
    overdue_rate: Decimal | None
    rates_add_vat: bool
