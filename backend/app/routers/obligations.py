import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.debt import DebtOut
from app.services import obligation_service

router = APIRouter(tags=["obligations"])


@router.delete("/obligations/{obligation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_obligation(
    obligation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    obligation_service.delete_obligation(db, user, obligation_id)


@router.post("/obligations/{obligation_id}/acknowledge", response_model=DebtOut)
def acknowledge_obligation(
    obligation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DebtOut:
    return DebtOut.from_model(obligation_service.acknowledge_obligation(db, user, obligation_id))
