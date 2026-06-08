from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel

FUTURE = (date.today() + timedelta(days=40)).isoformat()
PAST = (date.today() - timedelta(days=2)).isoformat()


@pytest.fixture
def catalog(db_session, seed_uy_currency):
    db_session.add_all([
        PriorityLevel(level=1, name="Ineludible", description="x"),
        PriorityLevel(level=2, name="Esencial", description="x"),
        PriorityLevel(level=3, name="Crítica", description="x"),
    ])
    db_session.flush()
    db_session.add_all([
        ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                       description="x", default_priority_level=2, visible=True),
        ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                       description="x", default_priority_level=3, visible=True),
    ])
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _recurrente(**over):
    body = {
        "obligation_type_id": 1, "priority_level": 2, "description": "Alquiler depto",
        "is_monthly_recurring": True, "due_day": 10, "currency_id": 1, "amount": "32000.00",
    }
    body.update(over)
    return body


def _unico(**over):
    body = {
        "obligation_type_id": 1, "priority_level": 3, "description": "Matrícula curso",
        "is_monthly_recurring": False, "first_due_date": FUTURE, "currency_id": 1, "amount": "12000.00",
    }
    body.update(over)
    return body


def _entries(db_session, obligation_id):
    return list(db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_type == "gasto",
                                    CashFlowEntry.source_id == obligation_id)
    ).scalars())


# --- POST ---

def test_post_recurrente_materializa(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_monthly_recurring"] is True
    assert body["amount"] == "32000.00"
    assert body["review_findings"] == []
    assert body["is_ready"] is True
    assert len(_entries(db_session, body["id"])) > 0  # materializó


def test_post_unico_una_entry(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_unico(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["due_day"] is None
    assert len(_entries(db_session, body["id"])) == 1


def test_post_kind_deuda_rechazado(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(obligation_type_id=10), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "expense_type_invalid"


def test_post_priority_sistema_rechazado(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(priority_level=1), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "priority_level_invalid"


def test_post_description_corta(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(description="corta"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "description_invalid"


def test_post_amount_invalido(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(amount="0"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "amount_invalid"


def test_post_due_day_fuera_de_rango(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(due_day=40), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "due_day_invalid"


def test_post_recurrente_sin_due_day(client, db_session, catalog):
    headers = _auth(client)
    body = _recurrente()
    del body["due_day"]
    resp = client.post("/expenses", json=body, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "expense_recurring_requires_due_day"


def test_post_recurrente_con_first_due_date(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(first_due_date=FUTURE), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "one_time_expense_inconsistent"


def test_post_unico_sin_first_due_date(client, db_session, catalog):
    headers = _auth(client)
    body = _unico()
    del body["first_due_date"]
    resp = client.post("/expenses", json=body, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "one_time_expense_inconsistent"


def test_post_unico_fecha_pasada(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_unico(first_due_date=PAST), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "one_time_date_in_past"


def test_post_moneda_otro_pais(client, db_session, catalog):
    from app.models.country import Country
    from app.models.currency import Currency
    db_session.add(Country(code="AR", name="Argentina", visible=True, vat_rate=Decimal("21.00")))
    db_session.flush()
    db_session.add(Currency(id=2, country_code="AR", name="Peso AR", is_legal_tender=True,
                            allowed_in_credit_card=False))
    db_session.flush()
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(currency_id=2), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "currency_not_available"


def test_post_sin_token(client, db_session, catalog):
    resp = client.post("/expenses", json=_recurrente())
    assert resp.status_code == 401


# --- GET ---

def test_get_lista_solo_gastos(client, db_session, catalog):
    headers = _auth(client)
    client.post("/expenses", json=_recurrente(description="Alquiler uno"), headers=headers)
    client.post("/expenses", json=_unico(description="Matrícula dos"), headers=headers)
    resp = client.get("/expenses", headers=headers)
    assert resp.status_code == 200
    expenses = resp.json()["expenses"]
    assert len(expenses) == 2


def test_get_vacio(client, db_session, catalog):
    headers = _auth(client)
    resp = client.get("/expenses", headers=headers)
    assert resp.json() == {"expenses": []}


def test_get_sin_token(client, db_session, catalog):
    assert client.get("/expenses").status_code == 401


def _create_recurrente(client, headers):
    return client.post("/expenses", json=_recurrente(), headers=headers).json()


def test_patch_cambia_amount(client, db_session, catalog):
    headers = _auth(client)
    exp = _create_recurrente(client, headers)
    resp = client.patch(f"/expenses/{exp['id']}", json={"amount": "35000.00"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["amount"] == "35000.00"
    assert any(e.amount == Decimal("35000.00") for e in _entries(db_session, exp["id"]))


def test_patch_cerrar_limpia_futuras(client, db_session, catalog):
    headers = _auth(client)
    exp = _create_recurrente(client, headers)
    assert len(_entries(db_session, exp["id"])) > 0
    resp = client.patch(f"/expenses/{exp['id']}", json={"is_closed": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_closed"] is True
    assert resp.json()["review_findings"] == []
    assert resp.json()["is_ready"] is True
    assert _entries(db_session, exp["id"]) == []  # motor limpió las futuras


def test_patch_recurrente_a_unico(client, db_session, catalog):
    headers = _auth(client)
    exp = _create_recurrente(client, headers)
    resp = client.patch(
        f"/expenses/{exp['id']}",
        json={"is_monthly_recurring": False, "due_day": None, "first_due_date": FUTURE},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_monthly_recurring"] is False
    assert resp.json()["first_due_date"] == FUTURE
    assert len(_entries(db_session, exp["id"])) == 1


def test_patch_estado_final_inconsistente(client, db_session, catalog):
    headers = _auth(client)
    exp = _create_recurrente(client, headers)
    # quitar due_day sin pasar a único → recurrente sin due_day
    resp = client.patch(f"/expenses/{exp['id']}", json={"due_day": None}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "expense_recurring_requires_due_day"


def test_patch_otro_usuario_404(client, db_session, catalog):
    headers_a = _auth(client, email="a@b.com")
    exp = _create_recurrente(client, headers_a)
    headers_b = _auth(client, email="b@b.com")
    resp = client.patch(f"/expenses/{exp['id']}", json={"amount": "1.00"}, headers=headers_b)
    assert resp.status_code == 404


def test_patch_vacio_ok(client, db_session, catalog):
    headers = _auth(client)
    exp = _create_recurrente(client, headers)
    resp = client.patch(f"/expenses/{exp['id']}", json={}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["amount"] == "32000.00"
