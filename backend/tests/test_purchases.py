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


def test_purchase_installments_roundtrip(client, db_session, seed_uy_currency):
    user, _ = _register(db_session, client)
    db_session.add(Purchase(
        user_id=user.id, purchase_date=date(2026, 6, 10),
        amount=Decimal("500.00"), currency_id=1, total_installments=6,
    ))
    db_session.commit()
    row = db_session.execute(select(Purchase)).scalars().one()
    assert row.total_installments == 6


from app.models.credit_card import CreditCard
from app.models.currency import Currency


def _card(db_session, user, deleted_at=None, institution_id=1):
    """Tarjeta del usuario. Requiere fixture seed_cc_refs (siembra institución 1 y red 1).

    Siembra el Dólar (3) idempotente: el motor lo necesita al materializar una compra con tarjeta.
    """
    if db_session.get(Currency, 3) is None:
        db_session.add(
            Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True)
        )
        db_session.flush()
    card = CreditCard(
        user_id=user.id, institution_id=institution_id, card_network_id=1, current_limit=Decimal("100000.00"),
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


def test_post_card_with_installments(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    r = client.post("/purchases", json=_body(credit_card_id=str(card.id), total_installments=6), headers=headers)
    assert r.status_code == 201
    assert r.json()["total_installments"] == 6


def test_post_cash_with_installments_invalid(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(total_installments=2), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "installments_invalid"


def test_post_cash_one_installment_ok(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(total_installments=1), headers=headers)
    assert r.status_code == 201
    assert r.json()["total_installments"] == 1


def test_post_zero_installments_invalid(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    r = client.post("/purchases", json=_body(credit_card_id=str(card.id), total_installments=0), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "installments_invalid"


def test_patch_to_cash_with_installments_rejected(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    created = _created(client, headers, credit_card_id=str(card.id), total_installments=3)
    r = client.patch(f"/purchases/{created['id']}", json={"credit_card_id": None}, headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "installments_invalid"


def test_patch_to_cash_clearing_installments_ok(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    created = _created(client, headers, credit_card_id=str(card.id), total_installments=3)
    body = {"credit_card_id": None, "total_installments": None}
    r = client.patch(f"/purchases/{created['id']}", json=body, headers=headers)
    assert r.status_code == 200
    assert r.json()["credit_card_id"] is None
    assert r.json()["total_installments"] is None


def test_patch_installments_null_back_to_single(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    created = _created(client, headers, credit_card_id=str(card.id), total_installments=3)
    r = client.patch(f"/purchases/{created['id']}", json={"total_installments": None}, headers=headers)
    assert r.status_code == 200
    assert r.json()["total_installments"] is None


def _statement(db_session, card):
    from app.models.credit_card_statement import CreditCardStatement

    st = CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=5,
        closing_date=date(2026, 5, 13), due_date=date(2026, 5, 25),
        total_local=Decimal("1000.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("100.00"), minimum_payment_usd=Decimal("0.00"),
    )
    db_session.add(st)
    db_session.commit()
    return st


def _entry_amounts(db_session, card):
    from app.models.cash_flow_entry import CashFlowEntry

    rows = db_session.execute(
        select(CashFlowEntry).where(
            CashFlowEntry.source_type == "tarjeta_credito",
            CashFlowEntry.source_id == card.id,
        )
    ).scalars()
    return {(e.issue_year, e.issue_month, e.currency_id): e.amount for e in rows}


def test_post_card_purchase_materializes(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    _statement(db_session, card)
    body = _body(credit_card_id=str(card.id), purchase_date="2026-06-10", amount="800.00")
    assert client.post("/purchases", json=body, headers=headers).status_code == 201
    assert _entry_amounts(db_session, card)[(2026, 6, 1)] == Decimal("800.00")


def test_post_cash_purchase_does_not_materialize(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    _statement(db_session, card)
    assert client.post("/purchases", json=_body(), headers=headers).status_code == 201
    assert _entry_amounts(db_session, card) == {}  # efectivo no dispara el engine


def test_patch_amount_rematerializes(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    _statement(db_session, card)
    created = _created(client, headers, credit_card_id=str(card.id), purchase_date="2026-06-10", amount="800.00")
    r = client.patch(f"/purchases/{created['id']}", json={"amount": "900.00"}, headers=headers)
    assert r.status_code == 200
    assert _entry_amounts(db_session, card)[(2026, 6, 1)] == Decimal("900.00")


def test_patch_to_cash_removes_from_projection(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    _statement(db_session, card)
    created = _created(client, headers, credit_card_id=str(card.id), purchase_date="2026-06-10", amount="800.00")
    r = client.patch(f"/purchases/{created['id']}", json={"credit_card_id": None}, headers=headers)
    assert r.status_code == 200
    assert _entry_amounts(db_session, card)[(2026, 6, 1)] == Decimal("0")


def test_delete_rematerializes(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    _statement(db_session, card)
    created = _created(client, headers, credit_card_id=str(card.id), purchase_date="2026-06-10", amount="800.00")
    assert client.delete(f"/purchases/{created['id']}", headers=headers).status_code == 204
    assert _entry_amounts(db_session, card)[(2026, 6, 1)] == Decimal("0")


def test_patch_change_card_rematerializes_both(client, db_session, seed_cc_refs):
    from app.models.institution import Institution

    user, headers = _register(db_session, client)
    db_session.add(Institution(id=2, country_code="UY", name="Itaú", visible=True))
    db_session.commit()
    card_a = _card(db_session, user)
    card_b = _card(db_session, user, institution_id=2)
    _statement(db_session, card_a)
    _statement(db_session, card_b)
    created = _created(client, headers, credit_card_id=str(card_a.id), purchase_date="2026-06-10", amount="800.00")
    r = client.patch(f"/purchases/{created['id']}", json={"credit_card_id": str(card_b.id)}, headers=headers)
    assert r.status_code == 200
    assert _entry_amounts(db_session, card_a)[(2026, 6, 1)] == Decimal("0")
    assert _entry_amounts(db_session, card_b)[(2026, 6, 1)] == Decimal("800.00")
