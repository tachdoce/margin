import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.cash_flow_payment import PaymentCreate, PaymentListItem, PaymentOut, PaymentUpdate
from app.services import cash_flow_payment_service as svc

router = APIRouter(tags=["cash-flow-payments"])


@router.post(
    "/cash-flow-entries/{entry_id}/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_payment(
    entry_id: uuid.UUID,
    payload: PaymentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOut:
    return PaymentOut.from_model(svc.create_payment(db, user, entry_id, payload))


@router.get("/cash-flow-entries/{entry_id}/payments")
def list_payments(
    entry_id: uuid.UUID,
    plan_id: uuid.UUID | None = Query(default=None),
    month: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PaymentListItem]:
    rows = svc.list_payments(db, user, entry_id, plan_id, month)
    return [PaymentListItem.from_model(p) for p in rows]


@router.patch("/cash-flow-entries/{entry_id}/payments/{payment_id}", response_model=PaymentOut)
def update_payment(
    entry_id: uuid.UUID,
    payment_id: uuid.UUID,
    payload: PaymentUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOut:
    return PaymentOut.from_model(svc.update_payment(db, user, entry_id, payment_id, payload))


@router.delete(
    "/cash-flow-entries/{entry_id}/payments/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_payment(
    entry_id: uuid.UUID,
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    svc.delete_payment(db, user, entry_id, payment_id)
