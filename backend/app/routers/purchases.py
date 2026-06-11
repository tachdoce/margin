import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.purchase import PurchaseCreate, PurchaseOut, PurchaseUpdate
from app.services import purchase_service

router = APIRouter(tags=["purchases"])


@router.post("/purchases", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
def create_purchase(
    payload: PurchaseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOut:
    return PurchaseOut.from_model(purchase_service.create_purchase(db, user, payload))


@router.get("/purchases")
def list_purchases(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"purchases": [PurchaseOut.from_model(p) for p in purchase_service.list_purchases(db, user)]}


@router.patch("/purchases/{purchase_id}", response_model=PurchaseOut)
def update_purchase(
    purchase_id: uuid.UUID,
    payload: PurchaseUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOut:
    return PurchaseOut.from_model(purchase_service.update_purchase(db, user, purchase_id, payload))


@router.delete("/purchases/{purchase_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase(
    purchase_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    purchase_service.delete_purchase(db, user, purchase_id)
