import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.cash_flow_entry import EntryAmountUpdate, SourceEntryOut, TimelineOut
from app.services import cash_flow_entry_service as svc

router = APIRouter(tags=["cash-flow-entries"])


@router.get("/cash-flow-entries", response_model=TimelineOut)
def get_timeline(
    plan_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TimelineOut:
    return svc.get_timeline(db, user, plan_id)


@router.get("/cash-flow-entries/by-source", response_model=list[SourceEntryOut])
def list_by_source(
    source_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SourceEntryOut]:
    return svc.list_by_source(db, user, source_id)


@router.patch("/cash-flow-entries/{entry_id}", response_model=SourceEntryOut)
def update_entry(
    entry_id: uuid.UUID,
    payload: EntryAmountUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SourceEntryOut:
    return svc.update_entry_amount(db, user, entry_id, payload.amount)
