import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.income import IncomeCreate, IncomeListOut, IncomeOut, IncomeUpdate
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


@router.get("/incomes", response_model=IncomeListOut)
def list_incomes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeListOut:
    incomes = income_service.list_incomes(db, user)
    return IncomeListOut(incomes=[IncomeOut.from_model(i) for i in incomes])


@router.delete("/incomes/{income_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_income(
    income_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    income_service.delete_income(db, user, income_id)


@router.post("/incomes/{income_id}/reactivate", response_model=IncomeOut)
def reactivate_income(
    income_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeOut:
    income = income_service.reactivate_income(db, user, income_id)
    return IncomeOut.from_model(income)
