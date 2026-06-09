import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.financing import FinancingCreate, FinancingOut, FinancingUpdate
from app.services import financing_service as svc

router = APIRouter(tags=["financings"])


@router.post("/financings", response_model=FinancingOut, status_code=status.HTTP_201_CREATED)
def create_financing(
    payload: FinancingCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FinancingOut:
    return FinancingOut.model_validate(svc.create_financing(db, user, payload))


@router.get("/financings")
def list_financings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FinancingOut]:
    return [FinancingOut.model_validate(f) for f in svc.list_financings(db, user)]


@router.patch("/financings/{financing_id}", response_model=FinancingOut)
def update_financing(
    financing_id: uuid.UUID,
    payload: FinancingUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FinancingOut:
    return FinancingOut.model_validate(svc.update_financing(db, user, financing_id, payload))


@router.delete("/financings/{financing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_financing(
    financing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    svc.delete_financing(db, user, financing_id)
