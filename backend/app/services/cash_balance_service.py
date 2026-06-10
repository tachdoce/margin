from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_balance import CashBalance
from app.models.user import User
from app.schemas.cash_balance import CashBalanceOut, CashBalancesSet
from app.services.scoping import holdable_currencies, require_holdable_currency


def get_balances(db: Session, user: User) -> list[CashBalanceOut]:
    stored = {
        b.currency_id: b.amount
        for b in db.execute(select(CashBalance).where(CashBalance.user_id == user.id)).scalars()
    }
    return [
        CashBalanceOut(currency_id=c.id, amount=stored.get(c.id, Decimal("0.00")))
        for c in holdable_currencies(db, user)
    ]


def set_balances(db: Session, user: User, payload: CashBalancesSet) -> list[CashBalanceOut]:
    # validar TODO el body antes de escribir (atómico)
    seen: set[int] = set()
    for item in payload.balances:
        if item.currency_id in seen:
            raise AppError(ErrorCode.duplicate_currency, field="currency_id")
        seen.add(item.currency_id)
        require_holdable_currency(db, user, item.currency_id)  # 422 currency_not_available
        if item.amount < 0:
            raise AppError(ErrorCode.amount_negative, field="amount")

    for item in payload.balances:
        row = db.get(CashBalance, (user.id, item.currency_id))
        if row is None:
            db.add(CashBalance(user_id=user.id, currency_id=item.currency_id, amount=item.amount))
        else:
            row.amount = item.amount
    db.flush()
    db.commit()
    return get_balances(db, user)
