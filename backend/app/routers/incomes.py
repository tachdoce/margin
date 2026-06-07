import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.income import IncomeCreate, IncomeOut, IncomeUpdate
from app.services import income_service

router = APIRouter(tags=["incomes"])


@router.post("/incomes", response_model=IncomeOut, status_code=status.HTTP_201_CREATED)
def create_income(
    payload: IncomeCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeOut:
    income = income_service.create_income(db, user, payload)
    return IncomeOut.from_model(income)


@router.patch("/incomes/{income_id}", response_model=IncomeOut)
def update_income(
    income_id: uuid.UUID,
    payload: IncomeUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeOut:
    income = income_service.update_income(db, user, income_id, payload)
    return IncomeOut.from_model(income)
