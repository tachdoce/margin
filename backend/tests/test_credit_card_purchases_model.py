# tests/test_credit_card_purchases_model.py
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.credit_card import CreditCard
from app.models.credit_card_purchase import CreditCardPurchase

from tests.test_credit_cards_model import _card_kwargs


def _make_card(db_session, user):
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    return card


def _purchase_kwargs(card, **over):
    base = dict(
        credit_card_id=card.id,
        description="Heladera",
        charge_date=date(2026, 1, 10),
        amount=Decimal("1997.50"),
        currency_id=1,
        total_installments=12,
        item_type_id=1,
        last_statement_closing_date=date(2026, 5, 13),
    )
    base.update(over)
    return base


def test_insert_installments_and_one_payment(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs)
    cuotas = CreditCardPurchase(**_purchase_kwargs(card))
    unico = CreditCardPurchase(**_purchase_kwargs(card, total_installments=None))
    db_session.add_all([cuotas, unico])
    db_session.flush()
    db_session.refresh(cuotas)
    db_session.refresh(unico)
    assert cuotas.total_installments == 12
    assert unico.total_installments is None


def test_invalid_card_fk(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs)
    import uuid

    db_session.add(CreditCardPurchase(**_purchase_kwargs(card, credit_card_id=uuid.uuid4())))
    with pytest.raises(IntegrityError):
        db_session.flush()
