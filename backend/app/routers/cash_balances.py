from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.cash_balance import CashBalanceOut, CashBalancesSet
from app.services import cash_balance_service as svc

router = APIRouter(tags=["cash-balances"])


@router.get("/cash-balances", response_model=list[CashBalanceOut])
def list_balances(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CashBalanceOut]:
    return svc.get_balances(db, user)


@router.put("/cash-balances", response_model=list[CashBalanceOut])
def set_balances(
    payload: CashBalancesSet,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CashBalanceOut]:
    return svc.set_balances(db, user, payload)
