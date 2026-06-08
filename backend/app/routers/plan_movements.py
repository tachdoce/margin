import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.plan_movement import PlanMovementCreate, PlanMovementOut, PlanMovementUpdate
from app.services import plan_movement_service

router = APIRouter(tags=["plan_movements"])


@router.post(
    "/plans/{plan_id}/movements", response_model=PlanMovementOut, status_code=status.HTTP_201_CREATED
)
def create_movement(
    plan_id: uuid.UUID,
    payload: PlanMovementCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanMovementOut:
    return PlanMovementOut.from_model(plan_movement_service.create_movement(db, user, plan_id, payload))


@router.get("/plans/{plan_id}/movements", response_model=list[PlanMovementOut])
def list_movements(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PlanMovementOut]:
    return [PlanMovementOut.from_model(m) for m in plan_movement_service.list_movements(db, user, plan_id)]


@router.patch("/plans/{plan_id}/movements/{movement_id}", response_model=PlanMovementOut)
def update_movement(
    plan_id: uuid.UUID,
    movement_id: uuid.UUID,
    payload: PlanMovementUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanMovementOut:
    return PlanMovementOut.from_model(
        plan_movement_service.update_movement(db, user, plan_id, movement_id, payload)
    )


@router.delete(
    "/plans/{plan_id}/movements/{movement_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_movement(
    plan_id: uuid.UUID,
    movement_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    plan_movement_service.delete_movement(db, user, plan_id, movement_id)
