import json
import uuid
from datetime import date as _date
from decimal import Decimal

from pydantic import BaseModel

from app.models.staging_credit_card import StagingCreditCard
from app.models.staging_credit_card_item import StagingCreditCardItem


class GeneralData(BaseModel):
    issuer: str | None = None
    card_network: str | None = None
    closing_date: _date | None = None
    due_date: _date | None = None
    current_limit: Decimal | None = None


class PaymentSummary(BaseModel):
    total_local: Decimal | None = None
    total_usd: Decimal | None = None
    minimum_payment_local: Decimal | None = None
    minimum_payment_usd: Decimal | None = None


class ChargeIn(BaseModel):
    date: _date | None = None
    description: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    current_installment: int | None = None
    total_installments: int | None = None


class AnnualEffectiveRates(BaseModel):
    vat_excluded: bool | None = None
    financing_rate_local_this_month: Decimal | None = None
    overdue_rate_local_this_month: Decimal | None = None
    financing_rate_usd_this_month: Decimal | None = None
    overdue_rate_usd_this_month: Decimal | None = None
    financing_rate_local_next_month: Decimal | None = None
    overdue_rate_local_next_month: Decimal | None = None
    financing_rate_usd_next_month: Decimal | None = None
    overdue_rate_usd_next_month: Decimal | None = None


class StagingStatementCreate(BaseModel):
    general_data: GeneralData = GeneralData()
    payment_summary: PaymentSummary = PaymentSummary()
    charges: list[ChargeIn] = []
    annual_effective_rates: AnnualEffectiveRates = AnnualEffectiveRates()
    # payments / others vienen en el payload pero no se declaran: Pydantic los ignora.


class StagingStatementItemOut(BaseModel):
    id: uuid.UUID
    charge_date: _date | None
    description: str | None
    amount: Decimal | None
    currency_id: int | None
    current_installment: int | None
    total_installments: int | None
    item_type_id: int | None
    missing_fields: list[str]

    @classmethod
    def from_model(cls, it: StagingCreditCardItem) -> "StagingStatementItemOut":
        mf: list[str] = []
        if it.charge_date is None:
            mf.append("charge_date")
        if it.description is None:
            mf.append("description")
        if it.amount is None:
            mf.append("amount")
        if it.currency_id is None:
            mf.append("currency_id")
        ci, ti = it.current_installment, it.total_installments
        if (ci is None) != (ti is None):  # solo uno de los dos
            mf.append("current_installment" if ci is None else "total_installments")
        if it.item_type_id is None:
            mf.append("item_type_id")
        return cls(
            id=it.id,
            charge_date=it.charge_date,
            description=it.description,
            amount=it.amount,
            currency_id=it.currency_id,
            current_installment=it.current_installment,
            total_installments=it.total_installments,
            item_type_id=it.item_type_id,
            missing_fields=mf,
        )


class StagingMadreOut(BaseModel):
    id: uuid.UUID
    institution_id: int | None
    card_network_id: int | None
    closing_date: _date | None
    due_date: _date | None
    current_limit: Decimal | None
    total_local: Decimal | None
    total_usd: Decimal | None
    minimum_payment_local: Decimal | None
    minimum_payment_usd: Decimal | None
    financing_rate_local: Decimal | None
    overdue_rate_local: Decimal | None
    financing_rate_usd: Decimal | None
    overdue_rate_usd: Decimal | None
    rates_add_vat: bool | None
    review_findings: list[str]
    is_ready: bool

    @classmethod
    def from_model(cls, m: StagingCreditCard) -> "StagingMadreOut":
        return cls(
            id=m.id,
            institution_id=m.institution_id,
            card_network_id=m.card_network_id,
            closing_date=m.closing_date,
            due_date=m.due_date,
            current_limit=m.current_limit,
            total_local=m.total_local,
            total_usd=m.total_usd,
            minimum_payment_local=m.minimum_payment_local,
            minimum_payment_usd=m.minimum_payment_usd,
            financing_rate_local=m.financing_rate_local,
            overdue_rate_local=m.overdue_rate_local,
            financing_rate_usd=m.financing_rate_usd,
            overdue_rate_usd=m.overdue_rate_usd,
            rates_add_vat=m.rates_add_vat,
            review_findings=json.loads(m.review_findings),
            is_ready=m.is_ready,
        )


class StagingStatementOut(StagingMadreOut):
    items: list[StagingStatementItemOut]

    @classmethod
    def from_model(
        cls, m: StagingCreditCard, items: list[StagingCreditCardItem]
    ) -> "StagingStatementOut":
        base = StagingMadreOut.from_model(m)
        return cls(
            **base.model_dump(),
            items=[StagingStatementItemOut.from_model(it) for it in items],
        )


class StagingMadreUpdate(BaseModel):
    institution_id: int | None = None
    card_network_id: int | None = None
    closing_date: _date | None = None
    due_date: _date | None = None
    current_limit: Decimal | None = None
    total_local: Decimal | None = None
    total_usd: Decimal | None = None
    minimum_payment_local: Decimal | None = None
    minimum_payment_usd: Decimal | None = None
    financing_rate_local: Decimal | None = None
    overdue_rate_local: Decimal | None = None
    financing_rate_usd: Decimal | None = None
    overdue_rate_usd: Decimal | None = None
    rates_add_vat: bool | None = None


class StagingItemUpdate(BaseModel):
    charge_date: _date | None = None
    description: str | None = None
    amount: Decimal | None = None
    currency_id: int | None = None
    item_type_id: int | None = None
    current_installment: int | None = None
    total_installments: int | None = None
