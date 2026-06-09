import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.credit_card import CreditCardOut, StatementItemOut, StatementOut
from app.services import credit_card_service

router = APIRouter(tags=["credit-cards"])


@router.get("/credit-cards")
def list_credit_cards(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    cards = credit_card_service.list_credit_cards(db, user)
    return {"credit_cards": [CreditCardOut.from_model(c) for c in cards]}


@router.get("/credit-cards/{card_id}/statements")
def list_statements(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    sts = credit_card_service.list_statements(db, user, card_id)
    return {"statements": [StatementOut.from_model(s) for s in sts]}


@router.get("/credit-cards/{card_id}/statements/{statement_id}/items")
def list_statement_items(
    card_id: uuid.UUID,
    statement_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = credit_card_service.list_statement_items(db, user, card_id, statement_id)
    return {"items": [StatementItemOut.from_model(it) for it in items]}
