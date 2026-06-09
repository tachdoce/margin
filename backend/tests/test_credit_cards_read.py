import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem
from app.models.user import User

from tests.test_credit_cards_model import _card_kwargs


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    return db_session.execute(select(User)).scalars().all()[-1]


def _make_card(db_session, user, **over):
    card = CreditCard(**{**_card_kwargs(user), **over})
    db_session.add(card)
    db_session.flush()
    return card


def _make_statement(db_session, card, *, issue_year=2026, issue_month=5, closing_day=13):
    s = CreditCardStatement(
        credit_card_id=card.id, issue_year=issue_year, issue_month=issue_month,
        closing_date=date(issue_year, issue_month, closing_day),
        due_date=date(issue_year, issue_month, 25),
        total_local=Decimal("100.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("10.00"), minimum_payment_usd=Decimal("0.00"),
    )
    db_session.add(s)
    db_session.flush()
    return s


# ---- GET /credit-cards ----

def test_list_empty(client, seed_cc_refs):
    headers = _auth(client)
    r = client.get("/credit-cards", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"credit_cards": []}


def test_list_vigente_y_soft_deleted(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    _make_card(db_session, user)  # vigente
    _make_card(db_session, user, institution_id=1, card_network_id=1, deleted_at=datetime.now(timezone.utc))
    r = client.get("/credit-cards", headers=headers)
    cards = r.json()["credit_cards"]
    assert len(cards) == 2
    assert sorted(c["is_deleted"] for c in cards) == [False, True]
    for c in cards:
        assert "reviewed_at" not in c and "deleted_at" not in c and "user_acknowledged_at" not in c
        assert isinstance(c["review_findings"], list)
    assert all("due_day" in c for c in cards)


def test_list_only_own(client, db_session, seed_cc_refs):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    _make_card(db_session, user_a)
    headers_b = _auth(client, email="b@b.com")
    r = client.get("/credit-cards", headers=headers_b)
    assert r.json() == {"credit_cards": []}


def test_list_401(client, seed_cc_refs):
    assert client.get("/credit-cards").status_code == 401


# ---- GET /credit-cards/{id}/statements ----

def test_statements_order_desc(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user)
    _make_statement(db_session, card, issue_year=2026, issue_month=4)
    _make_statement(db_session, card, issue_year=2026, issue_month=5)
    r = client.get(f"/credit-cards/{card.id}/statements", headers=headers)
    sts = r.json()["statements"]
    assert [(s["issue_year"], s["issue_month"]) for s in sts] == [(2026, 5), (2026, 4)]


def test_statements_404_other_user(client, db_session, seed_cc_refs):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a)
    headers_b = _auth(client, email="b@b.com")
    assert client.get(f"/credit-cards/{card.id}/statements", headers=headers_b).status_code == 404


def test_statements_soft_deleted_card(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, deleted_at=datetime.now(timezone.utc))
    _make_statement(db_session, card)
    r = client.get(f"/credit-cards/{card.id}/statements", headers=headers)
    assert r.status_code == 200 and len(r.json()["statements"]) == 1


def test_statements_empty(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user)
    r = client.get(f"/credit-cards/{card.id}/statements", headers=headers)
    assert r.json() == {"statements": []}


def test_statements_401(client, seed_cc_refs):
    assert client.get(f"/credit-cards/{uuid.uuid4()}/statements").status_code == 401


# ---- GET /credit-cards/{id}/statements/{statement_id}/items ----

def test_items_200(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user)
    st = _make_statement(db_session, card)
    db_session.add_all([
        CreditCardStatementItem(credit_card_statement_id=st.id, charge_date=date(2026, 2, 2),
                                description="SPORTLINE", amount=Decimal("1997.50"), currency_id=1,
                                current_installment=3, total_installments=4, item_type_id=1),
        CreditCardStatementItem(credit_card_statement_id=st.id, charge_date=date(2026, 4, 29),
                                description="GOOGLE", amount=Decimal("69.99"), currency_id=1,
                                current_installment=None, total_installments=None, item_type_id=1),
    ])
    db_session.flush()
    r = client.get(f"/credit-cards/{card.id}/statements/{st.id}/items", headers=headers)
    items = r.json()["items"]
    assert len(items) == 2
    assert any(i["description"] == "SPORTLINE" and i["total_installments"] == 4 for i in items)
    assert any(i["description"] == "GOOGLE" and i["total_installments"] is None for i in items)


def test_items_404_other_user(client, db_session, seed_cc_refs):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a)
    st = _make_statement(db_session, card)
    headers_b = _auth(client, email="b@b.com")
    assert client.get(f"/credit-cards/{card.id}/statements/{st.id}/items", headers=headers_b).status_code == 404


def test_items_404_statement_of_other_card(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card1 = _make_card(db_session, user)
    card2 = _make_card(db_session, user, deleted_at=datetime.now(timezone.utc))
    st2 = _make_statement(db_session, card2)
    assert client.get(f"/credit-cards/{card1.id}/statements/{st2.id}/items", headers=headers).status_code == 404


def test_items_401(client, seed_cc_refs):
    assert client.get(f"/credit-cards/{uuid.uuid4()}/statements/{uuid.uuid4()}/items").status_code == 401
