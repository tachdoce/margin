from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.credit_card_statement import StagingStatementCreate, StagingStatementOut
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
