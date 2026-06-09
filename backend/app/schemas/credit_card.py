import json
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem


class CreditCardOut(BaseModel):
    id: uuid.UUID
    institution_id: int
    card_network_id: int
    current_limit: Decimal
    closing_day: int
    financing_rate_local: Decimal
    overdue_rate_local: Decimal
    financing_rate_usd: Decimal
    overdue_rate_usd: Decimal
    rates_add_vat: bool
    review_findings: list[str]
    is_ready: bool
    is_deleted: bool

    @classmethod
    def from_model(cls, c: CreditCard) -> "CreditCardOut":
        return cls(
            id=c.id,
            institution_id=c.institution_id,
            card_network_id=c.card_network_id,
            current_limit=c.current_limit,
            closing_day=c.closing_day,
            financing_rate_local=c.financing_rate_local,
            overdue_rate_local=c.overdue_rate_local,
            financing_rate_usd=c.financing_rate_usd,
            overdue_rate_usd=c.overdue_rate_usd,
            rates_add_vat=c.rates_add_vat,
            review_findings=json.loads(c.review_findings),
            is_ready=c.is_ready,
            is_deleted=c.deleted_at is not None,
        )


class StatementOut(BaseModel):
    id: uuid.UUID
    issue_year: int
    issue_month: int
    closing_date: date
    due_date: date
    total_local: Decimal
    total_usd: Decimal
    minimum_payment_local: Decimal
    minimum_payment_usd: Decimal

    @classmethod
    def from_model(cls, s: CreditCardStatement) -> "StatementOut":
        return cls(
            id=s.id,
            issue_year=s.issue_year,
            issue_month=s.issue_month,
            closing_date=s.closing_date,
            due_date=s.due_date,
            total_local=s.total_local,
            total_usd=s.total_usd,
            minimum_payment_local=s.minimum_payment_local,
            minimum_payment_usd=s.minimum_payment_usd,
        )


class StatementItemOut(BaseModel):
    id: uuid.UUID
    charge_date: date
    description: str
    amount: Decimal
    currency_id: int
    current_installment: int | None
    total_installments: int | None
    item_type_id: int

    @classmethod
    def from_model(cls, it: CreditCardStatementItem) -> "StatementItemOut":
        return cls(
            id=it.id,
            charge_date=it.charge_date,
            description=it.description,
            amount=it.amount,
            currency_id=it.currency_id,
            current_installment=it.current_installment,
            total_installments=it.total_installments,
            item_type_id=it.item_type_id,
        )
