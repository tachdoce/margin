# tests/test_credit_card_statements_model.py
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement

from tests.test_credit_cards_model import _card_kwargs


def _make_card(db_session, user):
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    return card


def _statement_kwargs(card):
    return dict(
        credit_card_id=card.id,
        issue_year=2026,
        issue_month=5,
        closing_date=date(2026, 5, 13),
        due_date=date(2026, 5, 25),
        total_local=Decimal("7991.28"),
        total_usd=Decimal("65.35"),
        minimum_payment_local=Decimal("600.00"),
        minimum_payment_usd=Decimal("0.00"),
    )


def test_insert_and_read(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs)
    st = CreditCardStatement(**_statement_kwargs(card))
    db_session.add(st)
    db_session.flush()
    db_session.refresh(st)
    assert st.id is not None
    assert st.total_local == Decimal("7991.28")


def test_unique_period(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs)
    db_session.add(CreditCardStatement(**_statement_kwargs(card)))
    db_session.flush()
    db_session.add(CreditCardStatement(**_statement_kwargs(card)))  # mismo período
    with pytest.raises(IntegrityError):
        db_session.flush()
