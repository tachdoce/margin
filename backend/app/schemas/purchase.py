import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.purchase import Purchase


class PurchaseCreate(BaseModel):
    credit_card_id: uuid.UUID | None = None
    category_id: int | None = None
    description: str | None = None
    purchase_date: date
    amount: Decimal
    currency_id: int


class PurchaseUpdate(BaseModel):
    credit_card_id: uuid.UUID | None = None
    category_id: int | None = None
    description: str | None = None
    purchase_date: date | None = None
    amount: Decimal | None = None
    currency_id: int | None = None


class PurchaseOut(BaseModel):
    id: uuid.UUID
    credit_card_id: uuid.UUID | None
    category_id: int | None
    description: str | None
    purchase_date: date
    amount: Decimal
    currency_id: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, p: Purchase) -> "PurchaseOut":
        return cls(
            id=p.id,
            credit_card_id=p.credit_card_id,
            category_id=p.category_id,
            description=p.description,
            purchase_date=p.purchase_date,
            amount=p.amount,
            currency_id=p.currency_id,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
