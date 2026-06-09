import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.credit_card import CreditCard
from app.models.currency import Currency

from tests.test_credit_cards_read import _auth, _last_user, _make_card, _make_statement

T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def cc_full(db_session, seed_cc_refs):
    """seed_cc_refs + USD (Dólar 3) que el motor necesita al materializar."""
    db_session.add(
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True)
    )
    db_session.flush()


def _card_db(db_session, card_id):
    return db_session.execute(select(CreditCard).where(CreditCard.id == card_id)).scalar_one_or_none()


def _cc_entries(db_session, card_id):
    return db_session.execute(
        select(CashFlowEntry).where(
            CashFlowEntry.source_type == "tarjeta_credito", CashFlowEntry.source_id == card_id
        )
    ).scalars().all()


def test_reactivate_200(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, is_ready=True,
                      deleted_at=datetime.now(timezone.utc), closing_day=13)
    _make_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=13)
    card_id = card.id
    r = client.post(f"/credit-cards/{card_id}/reactivate", json={}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["is_deleted"] is False
    assert body["review_findings"] == []
    assert body["is_ready"] is True
    assert _card_db(db_session, card_id).deleted_at is None


def test_reactivate_materializes(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, is_ready=True,
                      deleted_at=datetime.now(timezone.utc), closing_day=13)
    _make_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=13)
    card_id = card.id
    client.post(f"/credit-cards/{card_id}/reactivate", json={}, headers=headers)
    assert len(_cc_entries(db_session, card_id)) >= 1


def test_reactivate_404_nonexistent(client, cc_full):
    headers = _auth(client)
    assert client.post(f"/credit-cards/{uuid.uuid4()}/reactivate", json={}, headers=headers).status_code == 404


def test_reactivate_404_other_user(client, db_session, cc_full):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a, created_at=T1, deleted_at=datetime.now(timezone.utc))
    headers_b = _auth(client, email="b@b.com")
    assert client.post(f"/credit-cards/{card.id}/reactivate", json={}, headers=headers_b).status_code == 404


def test_reactivate_409_not_deleted(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)  # vigente
    r = client.post(f"/credit-cards/{card.id}/reactivate", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "card_not_deleted"


def test_reactivate_409_already_exists(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    _make_card(db_session, user, created_at=T1)  # vigente (1,1)
    soft = _make_card(db_session, user, created_at=T1, institution_id=1, card_network_id=1,
                      deleted_at=datetime.now(timezone.utc))  # soft-deleted (1,1)
    soft_id = soft.id
    r = client.post(f"/credit-cards/{soft_id}/reactivate", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "card_already_exists"
    assert _card_db(db_session, soft_id).deleted_at is not None


def test_reactivate_closing_day_changed(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, is_ready=True,
                      deleted_at=datetime.now(timezone.utc), closing_day=13)
    _make_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=25)  # dif 12
    card_id = card.id
    r = client.post(f"/credit-cards/{card_id}/reactivate", json={}, headers=headers)
    assert r.json()["review_findings"] == ["closing_day_changed"]
    assert r.json()["is_ready"] is False
    assert _cc_entries(db_session, card_id) == []


def test_reactivate_401(client, cc_full):
    assert client.post(f"/credit-cards/{uuid.uuid4()}/reactivate", json={}).status_code == 401
