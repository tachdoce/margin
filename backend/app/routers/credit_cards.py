import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.credit_card import CreditCardOut, CreditCardUpdate, StatementItemOut, StatementOut
from app.services import credit_card_service

router = APIRouter(tags=["credit-cards"])


@router.get("/credit-cards")
def list_credit_cards(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    cards = credit_card_service.list_credit_cards(db, user)
    return {"credit_cards": [CreditCardOut.from_model(c) for c in cards]}


@router.patch("/credit-cards/{card_id}", response_model=CreditCardOut)
def update_credit_card(
    card_id: uuid.UUID,
    payload: CreditCardUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreditCardOut:
    return CreditCardOut.from_model(credit_card_service.update_credit_card(db, user, card_id, payload))


@router.post("/credit-cards/{card_id}/acknowledge", response_model=CreditCardOut)
def acknowledge_credit_card(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreditCardOut:
    return CreditCardOut.from_model(credit_card_service.acknowledge_credit_card(db, user, card_id))


@router.delete("/credit-cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credit_card(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    credit_card_service.delete_credit_card(db, user, card_id)


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


@router.delete("/credit-cards/{card_id}/statements", status_code=status.HTTP_204_NO_CONTENT)
def delete_last_statement(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    credit_card_service.delete_last_statement(db, user, card_id)


@router.post("/credit-cards/{card_id}/reactivate", response_model=CreditCardOut)
def reactivate_credit_card(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreditCardOut:
    return CreditCardOut.from_model(credit_card_service.reactivate_credit_card(db, user, card_id))
