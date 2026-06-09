from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.credit_card import CreditCard
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_network import CreditCardNetwork
from app.models.credit_card_purchase import CreditCardPurchase
from app.models.currency import Currency
from app.models.institution import Institution
from app.models.staging_credit_card import StagingCreditCard
from app.models.staging_credit_card_item import StagingCreditCardItem
from app.models.user import User

from tests.test_credit_cards_model import _card_kwargs

TODAY = date.today()
CLOSING = (TODAY - timedelta(days=5)).isoformat()
DUE = (TODAY + timedelta(days=10)).isoformat()


@pytest.fixture
def cc_catalog(db_session, seed_uy_currency):
    # seed_uy_currency siembra UY + Peso(1). Agregamos USD + emisor + red + tipos.
    db_session.add_all([
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True),
        Currency(id=4, country_code="UY", name="Unidad Indexada", is_legal_tender=False, allowed_in_credit_card=False),
        Institution(id=1, country_code="UY", name="Scotiabank", visible=True),
        CreditCardNetwork(id=1, country_code="UY", code="amex", name="Amex"),
        CreditCardItemType(id=1, code="compra", name="Compra", description="x"),
        CreditCardItemType(id=3, code="suscripcion", name="Suscripción", description="x"),
    ])
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _payload(**over):
    body = {
        "general_data": {
            "issuer": "Scotiabank", "card_network": "Amex",
            "closing_date": CLOSING, "due_date": DUE, "current_limit": 180000.00,
        },
        "payment_summary": {
            "total_local": 7991.28, "total_usd": 65.35,
            "minimum_payment_local": 600.00, "minimum_payment_usd": 0.00,
        },
        "charges": [
            {"date": "2026-02-02", "description": "SPORTLINE PUNTA", "amount": 1997.50,
             "currency": "Peso", "current_installment": 3, "total_installments": 4},
            {"date": "2026-04-29", "description": "GOOGLE *COM PULSO PULS", "amount": 69.99, "currency": "Dólar"},
        ],
        "payments": [], "others": [],
        "annual_effective_rates": {
            "vat_excluded": False,
            "financing_rate_local_this_month": 69.98, "overdue_rate_local_this_month": 81.27,
            "financing_rate_usd_this_month": 13.50, "overdue_rate_usd_this_month": 15.68,
            "financing_rate_local_next_month": 70.09, "overdue_rate_local_next_month": 81.39,
            "financing_rate_usd_next_month": 14.61, "overdue_rate_usd_next_month": 16.97,
        },
    }
    body.update(over)
    return body


def test_201_full_load(client, cc_catalog):
    headers = _auth(client)
    r = client.post("/credit-card-statements", json=_payload(), headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["institution_id"] == 1
    assert body["card_network_id"] == 1
    assert body["closing_date"] == CLOSING
    assert body["financing_rate_local"] == "70.09"   # COALESCE(next, this)
    assert body["rates_add_vat"] is True              # not vat_excluded
    items = body["items"]
    assert len(items) == 2
    by_cur = {it["currency_id"]: it for it in items}
    assert set(by_cur) == {1, 3}
    assert by_cur[1]["missing_fields"] == ["item_type_id"]
    assert by_cur[3]["missing_fields"] == ["item_type_id"]
    # reviewer corrió: sin tarjeta previa y emisor+red resueltos -> new_card
    assert body["review_findings"] == ["new_card"]
    assert body["is_ready"] is False


def test_resolution_to_null(client, cc_catalog):
    headers = _auth(client)
    p = _payload()
    p["general_data"]["issuer"] = "Banco Inexistente"
    p["general_data"]["card_network"] = "Nope"
    p["charges"][1]["currency"] = "Euro"
    r = client.post("/credit-card-statements", json=p, headers=headers)
    body = r.json()
    assert body["institution_id"] is None
    assert body["card_network_id"] is None
    google = next(it for it in body["items"] if it["description"].startswith("GOOGLE"))
    assert google["currency_id"] is None


def test_rates_fallback_to_this_month(client, cc_catalog):
    headers = _auth(client)
    p = _payload()
    p["annual_effective_rates"]["financing_rate_local_next_month"] = None
    r = client.post("/credit-card-statements", json=p, headers=headers)
    assert r.json()["financing_rate_local"] == "69.98"  # cae al this_month


def test_rates_both_null(client, cc_catalog):
    headers = _auth(client)
    p = _payload()
    p["annual_effective_rates"]["financing_rate_usd_next_month"] = None
    p["annual_effective_rates"]["financing_rate_usd_this_month"] = None
    r = client.post("/credit-card-statements", json=p, headers=headers)
    assert r.json()["financing_rate_usd"] is None


def test_rates_add_vat_absent_is_null(client, cc_catalog):
    headers = _auth(client)
    p = _payload()
    del p["annual_effective_rates"]["vat_excluded"]
    r = client.post("/credit-card-statements", json=p, headers=headers)
    assert r.json()["rates_add_vat"] is None


def test_upsert_overwrites(client, cc_catalog, db_session):
    headers = _auth(client)
    client.post("/credit-card-statements", json=_payload(), headers=headers)
    p2 = _payload()
    p2["charges"] = [{"date": "2026-03-03", "description": "OTRO", "amount": 10.0, "currency": "Peso"}]
    r = client.post("/credit-card-statements", json=p2, headers=headers)
    assert r.status_code == 201
    madres = db_session.execute(select(StagingCreditCard)).scalars().all()
    assert len(madres) == 1  # un solo staging por usuario
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["description"] == "OTRO"


def test_incomplete_item_missing_fields(client, cc_catalog):
    headers = _auth(client)
    p = _payload()
    p["charges"] = [{"description": "MERPAGO*ALGO", "current_installment": 2}]  # sin date/amount/currency, solo una cuota
    r = client.post("/credit-card-statements", json=p, headers=headers)
    mf = r.json()["items"][0]["missing_fields"]
    assert mf == ["charge_date", "amount", "currency_id", "total_installments", "item_type_id"]


def test_item_type_inheritance(client, cc_catalog, db_session):
    headers = _auth(client)
    user = db_session.execute(select(User)).scalars().first()
    card = CreditCard(**_card_kwargs(user))  # institución 1 + red 1
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardPurchase(
        credit_card_id=card.id, description="GOOGLE *COM PULSO PULS", charge_date=date(2026, 4, 29),
        amount=Decimal("69.99"), currency_id=3, total_installments=None, item_type_id=3,
        last_statement_closing_date=date(2026, 4, 13),
    ))
    db_session.flush()
    r = client.post("/credit-card-statements", json=_payload(), headers=headers)
    items = {it["description"]: it for it in r.json()["items"]}
    google = items["GOOGLE *COM PULSO PULS"]
    assert google["item_type_id"] == 3                 # heredado
    assert "item_type_id" not in google["missing_fields"]
    assert items["SPORTLINE PUNTA"]["item_type_id"] is None  # sin compra previa


def test_no_inheritance_without_resolved_card(client, cc_catalog, db_session):
    headers = _auth(client)
    user = db_session.execute(select(User)).scalars().first()
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardPurchase(
        credit_card_id=card.id, description="GOOGLE *COM PULSO PULS", charge_date=date(2026, 4, 29),
        amount=Decimal("69.99"), currency_id=3, total_installments=None, item_type_id=3,
        last_statement_closing_date=date(2026, 4, 13),
    ))
    db_session.flush()
    p = _payload()
    p["general_data"]["card_network"] = "Nope"  # red no resuelve -> no hay herencia
    r = client.post("/credit-card-statements", json=p, headers=headers)
    google = next(it for it in r.json()["items"] if it["description"].startswith("GOOGLE"))
    assert google["item_type_id"] is None


def test_401_without_token(client, cc_catalog):
    r = client.post("/credit-card-statements", json=_payload())
    assert r.status_code == 401


def _madre_body(**over):
    body = {
        "institution_id": 1, "card_network_id": 1,
        "closing_date": CLOSING, "due_date": DUE, "current_limit": 180000.00,
        "total_local": 7991.28, "total_usd": 65.35,
        "minimum_payment_local": 600.00, "minimum_payment_usd": 0.00,
        "financing_rate_local": 69.98, "overdue_rate_local": 81.27,
        "financing_rate_usd": 13.50, "overdue_rate_usd": 15.68,
        "rates_add_vat": True,
    }
    body.update(over)
    return body


def _item_body(**over):
    body = {
        "charge_date": "2026-05-03", "description": "MERPAGO*ALGO",
        "amount": 432.10, "currency_id": 1, "item_type_id": 1,
        "current_installment": 2, "total_installments": 6,
    }
    body.update(over)
    return body


def _post_staging(client, headers, **over):
    return client.post("/credit-card-statements", json=_payload(**over), headers=headers).json()


# ---- PUT madre ----

def test_put_madre_200(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(), headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["institution_id"] == 1
    assert body["total_local"] == "7991.28"
    assert "items" not in body  # respuesta madre-only
    assert isinstance(body["review_findings"], list)


def test_put_madre_404_no_staging(client, cc_catalog):
    headers = _auth(client)
    r = client.put("/credit-card-statements", json=_madre_body(), headers=headers)
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_put_madre_statement_incomplete(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(total_local=None), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "statement_incomplete"


def test_put_madre_institution_invalid(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(institution_id=999), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "institution_invalid"


def test_put_madre_card_network_invalid(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(card_network_id=999), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "card_network_invalid"


def test_put_madre_amount_invalid(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(current_limit=0), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "amount_invalid"
    r2 = client.put("/credit-card-statements", json=_madre_body(total_local=-1), headers=headers)
    assert r2.json()["code"] == "amount_invalid"


def test_put_madre_rates_null_ok(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(
        financing_rate_local=None, overdue_rate_local=None,
        financing_rate_usd=None, overdue_rate_usd=None,
    ), headers=headers)
    assert r.status_code == 200
    assert r.json()["financing_rate_local"] is None


def test_put_madre_inheritance_on_resolve(client, cc_catalog, db_session):
    headers = _auth(client)
    # POST con emisor/red que NO resuelven -> institution/network NULL, GOOGLE item type NULL
    _post_staging(client, headers, general_data={
        "issuer": "Desconocido", "card_network": "Nope",
        "closing_date": CLOSING, "due_date": DUE, "current_limit": 180000.00,
    })
    # existe una tarjeta del usuario + una compra GOOGLE clasificada (tipo 3)
    user = db_session.execute(select(User)).scalars().first()
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardPurchase(
        credit_card_id=card.id, description="GOOGLE *COM PULSO PULS", charge_date=date(2026, 4, 29),
        amount=Decimal("69.99"), currency_id=3, total_installments=None, item_type_id=3,
        last_statement_closing_date=date(2026, 4, 13),
    ))
    db_session.flush()
    # PUT resuelve emisor+red -> hereda el tipo a los ítems en NULL
    r = client.put("/credit-card-statements", json=_madre_body(), headers=headers)
    assert r.status_code == 200
    google = db_session.execute(
        select(StagingCreditCardItem).where(StagingCreditCardItem.description == "GOOGLE *COM PULSO PULS")
    ).scalars().first()
    assert google.item_type_id == 3


def test_put_madre_no_reinheritance_when_already_resolved(client, cc_catalog, db_session):
    headers = _auth(client)
    _post_staging(client, headers)  # emisor+red resuelven en el POST (institution 1, network 1)
    # recién ahora creamos tarjeta + compra GOOGLE: no debe heredarse en el PUT (ya estaba resuelta)
    user = db_session.execute(select(User)).scalars().first()
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardPurchase(
        credit_card_id=card.id, description="GOOGLE *COM PULSO PULS", charge_date=date(2026, 4, 29),
        amount=Decimal("69.99"), currency_id=3, total_installments=None, item_type_id=3,
        last_statement_closing_date=date(2026, 4, 13),
    ))
    db_session.flush()
    client.put("/credit-card-statements", json=_madre_body(), headers=headers)
    google = db_session.execute(
        select(StagingCreditCardItem).where(StagingCreditCardItem.description == "GOOGLE *COM PULSO PULS")
    ).scalars().first()
    assert google.item_type_id is None  # no se re-heredó


# ---- PUT ítem ----

def _first_item_id(post_body):
    return post_body["items"][0]["id"]


def test_put_item_200(client, cc_catalog):
    headers = _auth(client)
    body = _post_staging(client, headers)
    item_id = _first_item_id(body)
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(), headers=headers)
    assert r.status_code == 200
    out = r.json()
    assert out["missing_fields"] == []
    assert out["amount"] == "432.10"
    assert out["item_type_id"] == 1


def test_put_item_404_missing(client, cc_catalog):
    import uuid as _uuid
    headers = _auth(client)
    r = client.put(f"/credit-card-statements/items/{_uuid.uuid4()}", json=_item_body(), headers=headers)
    assert r.status_code == 404


def test_put_item_404_other_user(client, cc_catalog):
    headers_a = _auth(client, email="a@b.com")
    body = _post_staging(client, headers_a)
    item_id = _first_item_id(body)
    headers_b = _auth(client, email="b@b.com")
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(), headers=headers_b)
    assert r.status_code == 404


def test_put_item_incomplete(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(amount=None), headers=headers)
    assert r.json()["code"] == "item_incomplete"
    r2 = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(description="   "), headers=headers)
    assert r2.json()["code"] == "item_incomplete"


def test_put_item_currency_not_available(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(currency_id=4), headers=headers)
    assert r.json()["code"] == "currency_not_available"


def test_put_item_amount_invalid(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(amount=0), headers=headers)
    assert r.json()["code"] == "amount_invalid"


def test_put_item_type_invalid(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(item_type_id=999), headers=headers)
    assert r.json()["code"] == "item_type_invalid"


def test_put_item_installments_invalid(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}",
                   json=_item_body(current_installment=2, total_installments=None), headers=headers)
    assert r.json()["code"] == "installments_invalid"
    r2 = client.put(f"/credit-card-statements/items/{item_id}",
                    json=_item_body(current_installment=5, total_installments=3), headers=headers)
    assert r2.json()["code"] == "installments_invalid"


def test_put_item_one_payment_ok(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}",
                   json=_item_body(current_installment=None, total_installments=None), headers=headers)
    assert r.status_code == 200
    assert r.json()["current_installment"] is None


def test_put_401(client, cc_catalog):
    assert client.put("/credit-card-statements", json=_madre_body()).status_code == 401
    import uuid as _uuid
    assert client.put(f"/credit-card-statements/items/{_uuid.uuid4()}", json=_item_body()).status_code == 401


# ---- GET ----

def test_get_200(client, cc_catalog):
    headers = _auth(client)
    posted = _post_staging(client, headers)
    r = client.get("/credit-card-statements", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == posted["id"]
    assert len(body["items"]) == len(posted["items"])
    assert all("missing_fields" in it for it in body["items"])


def test_get_404_no_staging(client, cc_catalog):
    headers = _auth(client)
    assert client.get("/credit-card-statements", headers=headers).status_code == 404


def test_get_reflects_puts(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    client.put("/credit-card-statements", json=_madre_body(current_limit=999999.00), headers=headers)
    body = client.get("/credit-card-statements", headers=headers).json()
    assert body["current_limit"] == "999999.00"


def test_get_does_not_rereview(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    first = client.get("/credit-card-statements", headers=headers).json()
    second = client.get("/credit-card-statements", headers=headers).json()
    assert first["review_findings"] == second["review_findings"]
    assert first["is_ready"] == second["is_ready"]


# ---- DELETE ----

def test_delete_204(client, cc_catalog, db_session):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.delete("/credit-card-statements", headers=headers)
    assert r.status_code == 204
    assert client.get("/credit-card-statements", headers=headers).status_code == 404
    assert db_session.execute(select(StagingCreditCardItem)).scalars().all() == []  # cascade
    assert client.post("/credit-card-statements", json=_payload(), headers=headers).status_code == 201


def test_delete_404_no_staging(client, cc_catalog):
    headers = _auth(client)
    assert client.delete("/credit-card-statements", headers=headers).status_code == 404


# ---- acknowledge ----

def test_acknowledge_200(client, cc_catalog):
    headers = _auth(client)
    posted = _post_staging(client, headers)
    assert posted["review_findings"] == ["new_card"]
    r = client.post("/credit-card-statements/acknowledge", json={}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["review_findings"] == []
    assert body["is_ready"] is True
    assert "items" not in body


def test_acknowledge_404_no_staging(client, cc_catalog):
    headers = _auth(client)
    assert client.post("/credit-card-statements/acknowledge", json={}, headers=headers).status_code == 404


def test_acknowledge_409_no_findings(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    client.post("/credit-card-statements/acknowledge", json={}, headers=headers)
    r = client.post("/credit-card-statements/acknowledge", json={}, headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "statement_has_no_findings"


def test_acknowledge_then_get_stays_clean(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    client.post("/credit-card-statements/acknowledge", json={}, headers=headers)
    body = client.get("/credit-card-statements", headers=headers).json()
    assert body["review_findings"] == []
    assert body["is_ready"] is True


def test_chicos_401(client, cc_catalog):
    assert client.get("/credit-card-statements").status_code == 401
    assert client.delete("/credit-card-statements").status_code == 401
    assert client.post("/credit-card-statements/acknowledge", json={}).status_code == 401
