import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem
from app.models.currency import Currency

from tests.test_credit_cards_read import _auth, _last_user, _make_card, _make_statement
from tests.test_credit_cards_delete import _make_entry, _make_payment


@pytest.fixture
def cc_full(db_session, seed_cc_refs):
    """seed_cc_refs + USD (Dólar 3) que el motor necesita al materializar."""
    db_session.add(
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True)
    )
    db_session.flush()


def _make_item(db_session, statement):
    it = CreditCardStatementItem(
        credit_card_statement_id=statement.id, charge_date=date(2026, 5, 2),
        description="X", amount=Decimal("10.00"), currency_id=1,
        current_installment=None, total_installments=None, item_type_id=1,
    )
    db_session.add(it)
    db_session.flush()
    return it


def test_delete_last_204(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, is_ready=True)
    apr = _make_statement(db_session, card, issue_year=2026, issue_month=4, closing_day=13)
    may = _make_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=13)
    item = _make_item(db_session, may)
    card_id, may_id, apr_id, item_id = card.id, may.id, apr.id, item.id
    r = client.delete(f"/credit-cards/{card_id}/statements", headers=headers)
    assert r.status_code == 204
    assert db_session.execute(select(CreditCardStatement).where(CreditCardStatement.id == may_id)).scalar_one_or_none() is None
    assert db_session.execute(select(CreditCardStatement).where(CreditCardStatement.id == apr_id)).scalar_one_or_none() is not None
    assert db_session.execute(select(CreditCardStatementItem).where(CreditCardStatementItem.id == item_id)).scalar_one_or_none() is None


def test_delete_last_404_no_statements(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, is_ready=True)
    assert client.delete(f"/credit-cards/{card.id}/statements", headers=headers).status_code == 404


def test_delete_last_404_nonexistent(client, cc_full):
    headers = _auth(client)
    assert client.delete(f"/credit-cards/{uuid.uuid4()}/statements", headers=headers).status_code == 404


def test_delete_last_404_other_user(client, db_session, cc_full):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a, is_ready=True)
    _make_statement(db_session, card)
    headers_b = _auth(client, email="b@b.com")
    assert client.delete(f"/credit-cards/{card.id}/statements", headers=headers_b).status_code == 404


def test_delete_last_409_has_payments(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, is_ready=True)
    may = _make_statement(db_session, card, issue_year=2026, issue_month=5)
    entry = _make_entry(db_session, card, issue_month=5)
    _make_payment(db_session, entry, plan_id=None)
    may_id = may.id
    r = client.delete(f"/credit-cards/{card.id}/statements", headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "statement_has_payments"
    assert db_session.execute(select(CreditCardStatement).where(CreditCardStatement.id == may_id)).scalar_one_or_none() is not None


def test_delete_last_401(client, cc_full):
    assert client.delete(f"/credit-cards/{uuid.uuid4()}/statements").status_code == 401
