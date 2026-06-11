from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.auth_identity import AuthIdentity
from app.models.purchase import Purchase
from app.models.purchase_category import PurchaseCategory
from app.models.user import User


def _register(db_session, client, email="u@b.com"):
    """Registra un usuario vía API y devuelve (user, headers con token).

    Se resuelve el usuario por su identidad (email), no por created_at: en tests con
    seed_cc_refs conviven dos usuarios creados en la misma transacción y now() empata.
    """
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    identity = db_session.execute(
        select(AuthIdentity).where(AuthIdentity.identifier == email)
    ).scalars().one()
    user = db_session.get(User, identity.user_id)
    return user, {"Authorization": f"Bearer {token}"}


def _seed_categories(db_session):
    db_session.add_all([
        PurchaseCategory(id=1, code="comida", name="Comida", emoji="🍔"),
        PurchaseCategory(id=12, code="otros", name="Otros", emoji="🧩"),
    ])
    db_session.commit()


def test_purchase_category_roundtrip(db_session):
    db_session.add(PurchaseCategory(id=1, code="comida", name="Comida", emoji="🍔"))
    db_session.commit()
    row = db_session.get(PurchaseCategory, 1)
    assert row.code == "comida"
    assert row.emoji == "🍔"


def test_purchase_roundtrip_full(client, db_session, seed_uy_currency):
    _seed_categories(db_session)
    user, _ = _register(db_session, client)
    db_session.add(Purchase(
        user_id=user.id, category_id=1, description="Almuerzo",
        purchase_date=date(2026, 6, 10), amount=Decimal("450.00"), currency_id=1,
    ))
    db_session.commit()
    row = db_session.execute(select(Purchase)).scalars().one()
    assert row.amount == Decimal("450.00")
    assert row.credit_card_id is None
    assert row.category_id == 1


def test_purchase_roundtrip_nullables(client, db_session, seed_uy_currency):
    user, _ = _register(db_session, client)
    db_session.add(Purchase(
        user_id=user.id, purchase_date=date(2026, 6, 10),
        amount=Decimal("100.00"), currency_id=1,
    ))
    db_session.commit()
    row = db_session.execute(select(Purchase)).scalars().one()
    assert row.category_id is None
    assert row.description is None


from app.models.credit_card import CreditCard
from app.models.currency import Currency


def _card(db_session, user, deleted_at=None):
    """Tarjeta del usuario. Requiere fixture seed_cc_refs (siembra institución 1 y red 1)."""
    card = CreditCard(
        user_id=user.id, institution_id=1, card_network_id=1, current_limit=Decimal("100000.00"),
        closing_day=13, due_day=25, financing_rate_local=Decimal("10.00"),
        overdue_rate_local=Decimal("12.00"), financing_rate_usd=Decimal("5.00"),
        overdue_rate_usd=Decimal("6.00"), rates_add_vat=False,
        review_findings="[]", is_ready=True, deleted_at=deleted_at,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def _body(**overrides):
    body = {"purchase_date": "2026-06-10", "amount": "450.00", "currency_id": 1}
    body.update(overrides)
    return body


def test_post_requires_auth(client, db_session, seed_uy_currency):
    assert client.post("/purchases", json=_body()).status_code == 401


def test_post_cash_purchase(client, db_session, seed_uy_currency):
    _seed_categories(db_session)
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(category_id=1, description="Almuerzo"), headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["credit_card_id"] is None
    assert body["category_id"] == 1
    assert body["amount"] == "450.00"
    assert body["purchase_date"] == "2026-06-10"


def test_post_card_purchase(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    r = client.post("/purchases", json=_body(credit_card_id=str(card.id)), headers=headers)
    assert r.status_code == 201
    assert r.json()["credit_card_id"] == str(card.id)


def test_post_foreign_card_invalid(client, db_session, seed_cc_refs):
    other = seed_cc_refs  # usuario sembrado por la fixture, dueño de la tarjeta
    card = _card(db_session, other)
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(credit_card_id=str(card.id)), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "credit_card_invalid"


def test_post_deleted_card_invalid(client, db_session, seed_cc_refs):
    from datetime import datetime, timezone

    user, headers = _register(db_session, client)
    card = _card(db_session, user, deleted_at=datetime.now(timezone.utc))
    r = client.post("/purchases", json=_body(credit_card_id=str(card.id)), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "credit_card_invalid"


def test_post_unknown_category(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(category_id=999), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "purchase_category_invalid"


def test_post_without_category(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(), headers=headers)
    assert r.status_code == 201
    assert r.json()["category_id"] is None


def test_post_currency_not_holdable(client, db_session, seed_uy_currency):
    db_session.add(Currency(id=4, country_code="UY", name="UI", is_legal_tender=False, allowed_in_credit_card=False))
    db_session.commit()
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(currency_id=4), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "currency_not_available"


def test_post_amount_zero(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(amount="0.00"), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "amount_invalid"


def test_post_blank_description_stored_null(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(description="   "), headers=headers)
    assert r.status_code == 201
    assert r.json()["description"] is None


def test_get_requires_auth(client, db_session, seed_uy_currency):
    assert client.get("/purchases").status_code == 401


def test_get_only_own_ordered_desc(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    _, other_headers = _register(db_session, client, email="otro@b.com")
    client.post("/purchases", json=_body(purchase_date="2026-06-01", description="vieja"), headers=headers)
    client.post("/purchases", json=_body(purchase_date="2026-06-10", description="nueva"), headers=headers)
    client.post("/purchases", json=_body(description="ajena"), headers=other_headers)
    body = client.get("/purchases", headers=headers).json()
    assert [p["description"] for p in body["purchases"]] == ["nueva", "vieja"]


def _created(client, headers, **overrides):
    return client.post("/purchases", json=_body(**overrides), headers=headers).json()


def test_patch_category(client, db_session, seed_uy_currency):
    _seed_categories(db_session)
    _, headers = _register(db_session, client)
    created = _created(client, headers)
    r = client.patch(f"/purchases/{created['id']}", json={"category_id": 12}, headers=headers)
    assert r.status_code == 200
    assert r.json()["category_id"] == 12


def test_patch_card_to_cash(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    created = _created(client, headers, credit_card_id=str(card.id))
    r = client.patch(f"/purchases/{created['id']}", json={"credit_card_id": None}, headers=headers)
    assert r.status_code == 200
    assert r.json()["credit_card_id"] is None


def test_patch_empty(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    created = _created(client, headers)
    r = client.patch(f"/purchases/{created['id']}", json={}, headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "empty_patch"


def test_patch_purchase_date_null(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    created = _created(client, headers)
    r = client.patch(f"/purchases/{created['id']}", json={"purchase_date": None}, headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "field_not_nullable"


def test_patch_foreign_404(client, db_session, seed_uy_currency):
    _seed_categories(db_session)
    _, headers = _register(db_session, client)
    _, other_headers = _register(db_session, client, email="otro@b.com")
    created = _created(client, headers)
    r = client.patch(f"/purchases/{created['id']}", json={"category_id": 1}, headers=other_headers)
    assert r.status_code == 404


def test_delete_hard(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    created = _created(client, headers)
    r = client.delete(f"/purchases/{created['id']}", headers=headers)
    assert r.status_code == 204
    assert client.get("/purchases", headers=headers).json()["purchases"] == []


def test_delete_foreign_404(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    _, other_headers = _register(db_session, client, email="otro@b.com")
    created = _created(client, headers)
    assert client.delete(f"/purchases/{created['id']}", headers=other_headers).status_code == 404
