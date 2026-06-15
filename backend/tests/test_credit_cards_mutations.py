from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.credit_card import CreditCard
from app.models.credit_card_network import CreditCardNetwork
from app.models.currency import Currency
from app.models.institution import Institution

from tests.test_credit_cards_read import _auth, _last_user, _make_card, _make_statement

T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 2, 1, tzinfo=timezone.utc)


@pytest.fixture
def cc_full(db_session, seed_cc_refs):
    """seed_cc_refs (Peso 1, institución 1, red 1, tipo 1) + USD (Dólar 3) que el motor necesita."""
    db_session.add(
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True)
    )
    db_session.flush()


# ---- PATCH ----

def test_patch_closing_day_ok(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)  # existente (created_at != updated_at)
    r = client.patch(f"/credit-cards/{card.id}", json={"closing_day": 15}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["closing_day"] == 15
    assert body["review_findings"] == []  # sin statement -> rama existente sin closing_day_changed
    assert body["is_ready"] is True


def test_patch_404_other_user(client, db_session, cc_full):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a, created_at=T1)
    headers_b = _auth(client, email="b@b.com")
    assert client.patch(f"/credit-cards/{card.id}", json={"closing_day": 15}, headers=headers_b).status_code == 404


def test_patch_404_soft_deleted(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, deleted_at=datetime.now(timezone.utc))
    assert client.patch(f"/credit-cards/{card.id}", json={"closing_day": 15}, headers=headers).status_code == 404


def test_patch_empty(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    r = client.patch(f"/credit-cards/{card.id}", json={}, headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "empty_patch"


def test_patch_institution_invalid(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    r = client.patch(f"/credit-cards/{card.id}", json={"institution_id": 999}, headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "institution_invalid"


def test_patch_card_network_invalid(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    r = client.patch(f"/credit-cards/{card.id}", json={"card_network_id": 999}, headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "card_network_invalid"


def test_patch_closing_day_invalid(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    assert client.patch(f"/credit-cards/{card.id}", json={"closing_day": 0}, headers=headers).json()["code"] == "closing_day_invalid"
    assert client.patch(f"/credit-cards/{card.id}", json={"closing_day": 32}, headers=headers).json()["code"] == "closing_day_invalid"


def test_patch_card_already_exists(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    # otra institución/red para mover la combinación
    db_session.add_all([
        Institution(id=2, country_code="UY", name="BROU", visible=True),
        CreditCardNetwork(id=2, country_code="UY", code="visa", name="Visa"),
    ])
    db_session.flush()
    _make_card(db_session, user, created_at=T1)  # institución 1 + red 1 (vigente)
    other = _make_card(db_session, user, created_at=T1, institution_id=2, card_network_id=2)
    # mover `other` a (1,1) choca con la primera
    r = client.patch(f"/credit-cards/{other.id}", json={"institution_id": 1, "card_network_id": 1}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "card_already_exists"


def test_patch_closing_day_changed(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, closing_day=13)
    _make_statement(db_session, card, issue_year=2026, issue_month=4, closing_day=13)
    r = client.patch(f"/credit-cards/{card.id}", json={"closing_day": 25}, headers=headers)  # dif 12
    assert r.json()["review_findings"] == ["closing_day_changed"]
    assert r.json()["is_ready"] is False


def test_patch_due_day_ok(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    r = client.patch(f"/credit-cards/{card.id}", json={"due_day": 20}, headers=headers)
    assert r.status_code == 200
    assert r.json()["due_day"] == 20


def test_patch_due_day_invalid(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    assert client.patch(f"/credit-cards/{card.id}", json={"due_day": 0}, headers=headers).json()["code"] == "due_day_invalid"
    assert client.patch(f"/credit-cards/{card.id}", json={"due_day": 32}, headers=headers).json()["code"] == "due_day_invalid"


def test_patch_401(client, cc_full):
    import uuid
    assert client.patch(f"/credit-cards/{uuid.uuid4()}", json={"closing_day": 15}).status_code == 401


# ---- acknowledge ----

def test_ack_new_card_graduates(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    # nueva: created_at == updated_at (server default, misma tx) + finding
    card = _make_card(db_session, user, review_findings='["closing_day_inferred"]', is_ready=False)
    assert card.created_at == card.updated_at
    r = client.post(f"/credit-cards/{card.id}/acknowledge", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["review_findings"] == [] and r.json()["is_ready"] is True
    db_session.refresh(card)
    assert card.updated_at != card.created_at  # se graduó de "nueva"


def test_ack_existing_preserves_updated_at(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, updated_at=T2,
                      review_findings='["closing_day_changed"]', is_ready=False)
    client.post(f"/credit-cards/{card.id}/acknowledge", json={}, headers=headers)
    db_session.refresh(card)
    assert card.updated_at == T2  # se preservó


def test_ack_404_soft_deleted(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, deleted_at=datetime.now(timezone.utc),
                      review_findings='["closing_day_inferred"]', is_ready=False)
    assert client.post(f"/credit-cards/{card.id}/acknowledge", json={}, headers=headers).status_code == 404


def test_ack_409_no_findings(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)  # review_findings '[]' por defecto
    r = client.post(f"/credit-cards/{card.id}/acknowledge", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "card_has_no_findings"


def test_ack_401(client, cc_full):
    import uuid
    assert client.post(f"/credit-cards/{uuid.uuid4()}/acknowledge", json={}).status_code == 401


# ---- prioridad (slice 2) ----

def test_patch_card_priority_y_regla(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    r = client.patch(f"/credit-cards/{card.id}",
                     json={"payment_rule": "minimo", "priority": 1}, headers=headers)
    assert r.status_code == 200
    assert r.json()["payment_rule"] == "minimo" and r.json()["priority"] == 1


def test_patch_card_regla_sin_priority_rechaza(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    r = client.patch(f"/credit-cards/{card.id}", json={"payment_rule": "total"}, headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "payment_rule_invalid"
