import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.credit_card import CreditCard
from app.models.credit_card_purchase import CreditCardPurchase
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem

from tests.test_credit_cards_read import _auth, _last_user, _make_card, _make_statement


def _make_item(db_session, statement, **over):
    it = CreditCardStatementItem(
        credit_card_statement_id=statement.id, charge_date=date(2026, 2, 2),
        description="X", amount=Decimal("100.00"), currency_id=1,
        current_installment=None, total_installments=None, item_type_id=1,
    )
    for k, v in over.items():
        setattr(it, k, v)
    db_session.add(it)
    db_session.flush()
    return it


def _make_purchase(db_session, card):
    p = CreditCardPurchase(
        credit_card_id=card.id, description="X", charge_date=date(2026, 2, 2),
        amount=Decimal("100.00"), currency_id=1, total_installments=None, item_type_id=1,
        last_statement_closing_date=date(2026, 5, 13),
    )
    db_session.add(p)
    db_session.flush()
    return p


def _make_entry(db_session, card, **over):
    e = CashFlowEntry(
        user_id=card.user_id, event_date=date(2026, 5, 25), is_income=False,
        amount=Decimal("100.00"), currency_id=1, issue_year=2026, issue_month=5,
        source_type="tarjeta_credito", source_id=card.id,
    )
    for k, v in over.items():
        setattr(e, k, v)
    db_session.add(e)
    db_session.flush()
    return e


def _make_payment(db_session, entry, plan_id=None):
    p = CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("10.00"), plan_id=plan_id)
    db_session.add(p)
    db_session.flush()
    return p


def _card_exists(db_session, card_id):
    return db_session.execute(select(CreditCard).where(CreditCard.id == card_id)).scalar_one_or_none()


def test_hard_delete(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user)
    st = _make_statement(db_session, card)
    _make_item(db_session, st)
    _make_purchase(db_session, card)
    _make_entry(db_session, card)  # sin pagos -> count real 0 -> hard
    card_id, st_id = card.id, st.id  # capturar antes del delete (el commit expira los objetos)
    r = client.delete(f"/credit-cards/{card_id}", headers=headers)
    assert r.status_code == 204
    assert _card_exists(db_session, card_id) is None
    assert db_session.execute(select(CreditCardStatement).where(CreditCardStatement.credit_card_id == card_id)).scalars().all() == []
    assert db_session.execute(select(CreditCardStatementItem).where(CreditCardStatementItem.credit_card_statement_id == st_id)).scalars().all() == []
    assert db_session.execute(select(CreditCardPurchase).where(CreditCardPurchase.credit_card_id == card_id)).scalars().all() == []
    assert db_session.execute(select(CashFlowEntry).where(CashFlowEntry.source_type == "tarjeta_credito", CashFlowEntry.source_id == card_id)).scalars().all() == []


def test_soft_delete(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user)
    st = _make_statement(db_session, card)
    _make_purchase(db_session, card)
    entry_paid = _make_entry(db_session, card, issue_month=5)
    _make_payment(db_session, entry_paid, plan_id=None)  # pago real
    entry_unpaid = _make_entry(db_session, card, issue_month=6, event_date=date(2026, 6, 25))  # sin pago
    card_id, paid_id, unpaid_id = card.id, entry_paid.id, entry_unpaid.id  # capturar antes del delete
    r = client.delete(f"/credit-cards/{card_id}", headers=headers)
    assert r.status_code == 204
    card_db = _card_exists(db_session, card_id)
    assert card_db is not None and card_db.deleted_at is not None  # soft-deleted
    assert _entry_exists(db_session, paid_id) is not None    # sobrevive
    assert _entry_exists(db_session, unpaid_id) is None      # se borró
    assert db_session.execute(select(CreditCardStatement).where(CreditCardStatement.credit_card_id == card_id)).scalars().all() != []
    assert db_session.execute(select(CreditCardPurchase).where(CreditCardPurchase.credit_card_id == card_id)).scalars().all() != []


def _entry_exists(db_session, entry_id):
    return db_session.execute(select(CashFlowEntry).where(CashFlowEntry.id == entry_id)).scalar_one_or_none()


def test_delete_404_nonexistent(client, seed_cc_refs):
    headers = _auth(client)
    assert client.delete(f"/credit-cards/{uuid.uuid4()}", headers=headers).status_code == 404


def test_delete_404_other_user(client, db_session, seed_cc_refs):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a)
    headers_b = _auth(client, email="b@b.com")
    assert client.delete(f"/credit-cards/{card.id}", headers=headers_b).status_code == 404


def test_delete_404_already_soft_deleted(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, deleted_at=datetime.now(timezone.utc))
    assert client.delete(f"/credit-cards/{card.id}", headers=headers).status_code == 404


def test_delete_401(client, seed_cc_refs):
    assert client.delete(f"/credit-cards/{uuid.uuid4()}").status_code == 401
