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
