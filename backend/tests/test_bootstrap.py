from decimal import Decimal

from app.models.country import Country
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_network import CreditCardNetwork
from app.models.currency import Currency
from app.models.income_type import IncomeType
from app.models.institution import Institution
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.review_finding_code import ReviewFindingCode

CATALOG_KEYS = {
    "currencies", "obligation_types", "income_types", "priority_levels",
    "institutions", "review_finding_codes", "credit_card_networks", "credit_card_item_types",
}


def _seed_catalogs(db_session):
    # segundo país para probar el filtrado por país
    db_session.add(Country(code="AR", name="Argentina", visible=True, vat_rate=Decimal("21.00")))
    # PriorityLevel primero (ObligationType tiene FK a priority_levels)
    db_session.add_all([
        PriorityLevel(level=1, name="Ineludible", description="x"),
        PriorityLevel(level=2, name="Esencial", description="x"),
    ])
    db_session.flush()
    db_session.add_all([
        Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True,
                 symbol="$", display_decimals=0),
        Currency(id=99, country_code="AR", name="Peso AR", is_legal_tender=True, allowed_in_credit_card=False),
        IncomeType(id=1, code="sueldo", name="Sueldo", visible=True),
        IncomeType(id=2, code="oculto", name="Oculto", visible=False),
        ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler", description="x", default_priority_level=2, visible=True),
        ObligationType(id=2, obligation_kind="gasto", code="oculto_ot", name="Oculto", description="x", default_priority_level=2, visible=False),
        Institution(id=1, country_code="UY", name="BROU", visible=True),
        Institution(id=2, country_code="AR", name="Banco AR", visible=True),
        ReviewFindingCode(code="amount_above_threshold", message="x"),
        CreditCardNetwork(id=1, country_code="UY", code="visa", name="Visa"),
        CreditCardItemType(id=1, code="compra", name="Compra", description="x"),
    ])
    db_session.flush()


def _register_token(client):
    return client.post("/auth/register", json={"email": "u@b.com", "password": "12345678"}).json()["token"]


def test_bootstrap_requires_auth(client, seed_uy):
    resp = client.get("/bootstrap")
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_bootstrap_returns_catalogs(client, db_session, seed_uy):
    _seed_catalogs(db_session)
    token = _register_token(client)

    resp = client.get("/bootstrap", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"]
    catalogs = body["catalogs"]
    assert set(catalogs.keys()) == CATALOG_KEYS
    # filtrado por país: solo data de UY
    assert {c["name"] for c in catalogs["currencies"]} == {"Peso"}
    peso = next(c for c in catalogs["currencies"] if c["name"] == "Peso")
    assert peso["allowed_in_credit_card"] is True  # expuesto para los selects de tarjetas
    assert peso["symbol"] == "$"
    assert peso["display_decimals"] == 0
    assert {i["name"] for i in catalogs["institutions"]} == {"BROU"}
    # priority_levels: todos (incluye el nivel 1)
    levels = {p["level"] for p in catalogs["priority_levels"]}
    assert 1 in levels and 2 in levels
    # income_types: el visible=false no aparece
    assert all(it["code"] != "oculto" for it in catalogs["income_types"])
    # obligation_types: el visible=false no aparece
    assert all(ot["code"] != "oculto_ot" for ot in catalogs["obligation_types"])
    # tipos editables expuestos desde el backend (single source of truth)
    from app.services.cash_flow_entry_service import EDITABLE_ENTRY_SOURCE_TYPES
    assert body["editable_entry_source_types"] == list(EDITABLE_ENTRY_SOURCE_TYPES)
