import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.expense import ExpenseCreate, ExpenseOut, ExpenseUpdate
from app.services import expense_service

router = APIRouter(tags=["expenses"])


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExpenseOut:
    return ExpenseOut.from_model(expense_service.create_expense(db, user, payload))


@router.get("/expenses")
def list_expenses(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"expenses": [ExpenseOut.from_model(o) for o in expense_service.list_expenses(db, user)]}


@router.patch("/expenses/{obligation_id}", response_model=ExpenseOut)
def update_expense(
    obligation_id: uuid.UUID,
    payload: ExpenseUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExpenseOut:
    return ExpenseOut.from_model(expense_service.update_expense(db, user, obligation_id, payload))
