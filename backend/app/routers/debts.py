import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.debt import DebtCreate, DebtOut, DebtUpdate
from app.services import debt_service

router = APIRouter(tags=["debts"])


@router.post("/debts", response_model=DebtOut, status_code=status.HTTP_201_CREATED)
def create_debt(
    payload: DebtCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DebtOut:
    return DebtOut.from_model(debt_service.create_debt(db, user, payload))


@router.get("/debts")
def list_debts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"debts": [DebtOut.from_model(o) for o in debt_service.list_debts(db, user)]}


@router.patch("/debts/{obligation_id}", response_model=DebtOut)
def update_debt(
    obligation_id: uuid.UUID,
    payload: DebtUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DebtOut:
    return DebtOut.from_model(debt_service.update_debt(db, user, obligation_id, payload))
