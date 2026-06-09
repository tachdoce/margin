import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.cash_flow_entry import TimelineOut
from app.services import cash_flow_entry_service as svc

router = APIRouter(tags=["cash-flow-entries"])


@router.get("/cash-flow-entries", response_model=TimelineOut)
def get_timeline(
    plan_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TimelineOut:
    return svc.get_timeline(db, user, plan_id)
