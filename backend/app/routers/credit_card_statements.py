import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.credit_card_statement import (
    StagingItemUpdate,
    StagingMadreOut,
    StagingMadreUpdate,
    StagingStatementCreate,
    StagingStatementItemOut,
    StagingStatementOut,
)
from app.services import credit_card_statement_service

router = APIRouter(tags=["credit-card-statements"])


@router.post(
    "/credit-card-statements", response_model=StagingStatementOut, status_code=status.HTTP_201_CREATED
)
def create_staging_statement(
    payload: StagingStatementCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StagingStatementOut:
    madre, items = credit_card_statement_service.create_staging_statement(db, user, payload)
    return StagingStatementOut.from_model(madre, items)


@router.put("/credit-card-statements", response_model=StagingMadreOut)
def update_staging_madre(
    payload: StagingMadreUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StagingMadreOut:
    return StagingMadreOut.from_model(credit_card_statement_service.update_staging_madre(db, user, payload))


@router.put("/credit-card-statements/items/{item_id}", response_model=StagingStatementItemOut)
def update_staging_item(
    item_id: uuid.UUID,
    payload: StagingItemUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StagingStatementItemOut:
    return StagingStatementItemOut.from_model(
        credit_card_statement_service.update_staging_item(db, user, item_id, payload)
    )
