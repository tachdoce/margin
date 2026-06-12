import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.plan import PlanCopyRequest, PlanCreate, PlanOut, PlanUpdate
from app.services import plan_service, planning

router = APIRouter(tags=["plans"])


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: PlanCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanOut:
    return PlanOut.from_model(plan_service.create_plan(db, user, payload))


@router.get("/plans", response_model=list[PlanOut])
def list_plans(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PlanOut]:
    return [PlanOut.from_model(p) for p in plan_service.list_plans(db, user)]


@router.patch("/plans/{plan_id}", response_model=PlanOut)
def update_plan(
    plan_id: uuid.UUID,
    payload: PlanUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanOut:
    return PlanOut.from_model(plan_service.update_plan(db, user, plan_id, payload))


@router.post("/plans/{plan_id}/select", response_model=PlanOut)
def select_plan(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanOut:
    return PlanOut.from_model(plan_service.select_plan(db, user, plan_id))


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    plan_service.delete_plan(db, user, plan_id)


@router.post("/plans/{plan_id}/copy", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def copy_plan(
    plan_id: uuid.UUID,
    payload: PlanCopyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanOut:
    return PlanOut.from_model(plan_service.copy_plan(db, user, plan_id, payload))


@router.post("/plans/{plan_id}/planning", status_code=status.HTTP_204_NO_CONTENT)
def run_planning(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    planning.run_planning(db, user, plan_id)


@router.delete("/plans/{plan_id}/planning", status_code=status.HTTP_204_NO_CONTENT)
def clear_planning(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    planning.clear_planning(db, user, plan_id)
