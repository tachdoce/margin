from decimal import Decimal

from pydantic import BaseModel


class CashBalanceOut(BaseModel):
    currency_id: int
    amount: Decimal


class CashBalanceSetItem(BaseModel):
    currency_id: int
    amount: Decimal


class CashBalancesSet(BaseModel):
    balances: list[CashBalanceSetItem]
    monthly_need_amount: Decimal | None = None


class CashBalancesView(BaseModel):
    balances: list[CashBalanceOut]
    monthly_need_amount: Decimal | None
