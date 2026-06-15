from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.country import Country
from app.models.currency import Currency
from app.models.institution import Institution
from app.models.obligation_type import ObligationType

CRON_FIRST = (date.today() + timedelta(days=20)).isoformat()   # cronograma: arranca futuro
ONE_TIME = (date.today() + timedelta(days=60)).isoformat()     # pago único futuro


@pytest.fixture
def catalog(db_session, seed_uy_currency):
    db_session.add_all([
    ])
    db_session.flush()
    db_session.add_all([
        ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                       description="x", visible=True),
        ObligationType(id=8, obligation_kind="deuda_abierta", code="informal", name="Informal",
                       description="x", visible=True),
        ObligationType(id=9, obligation_kind="deuda_abierta", code="otra_abierta", name="Otra",
                       description="x", visible=True),  # no-informal
        ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                       description="x", visible=True),
    ])
    db_session.flush()
    db_session.add(Institution(id=1, country_code="UY", name="Banco UY", visible=True))
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _cronograma(**over):
    body = {
        "obligation_type_id": 10, "institution_id": 1,
        "description": "Préstamo personal banco", "due_day": 10, "currency_id": 1,
        "amount": "6250.00", "total_installments": 24, "first_due_date": CRON_FIRST,
        "financing_rate": "45.00", "overdue_rate": "60.00", "rates_add_vat": True,
    }
    body.update(over)
    return body


def _pago_unico(**over):
    body = {
        "obligation_type_id": 10, "description": "Préstamo familiar",
        "currency_id": 1, "amount": "30000.00", "first_due_date": ONE_TIME,
    }
    body.update(over)
    return body


def _abierta(**over):
    body = {
        "obligation_type_id": 8, "description": "Plata que le debo a mi viejo",
        "currency_id": 1, "amount": "50000.00",
    }
    body.update(over)
    return body


def _entries(db_session, obligation_id, source_type="deuda"):
    return list(db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_type == source_type,
                                    CashFlowEntry.source_id == obligation_id)
    ).scalars())


# --- POST deuda ---

def test_post_cronograma_materializa(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_monthly_recurring"] is False
    assert body["total_installments"] == 24
    assert body["financing_rate"] == "45.00"
    assert body["review_findings"] == []
    assert body["is_ready"] is True
    assert len(_entries(db_session, body["id"])) > 0


def test_post_pago_unico_una_entry(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_pago_unico(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["total_installments"] is None
    assert body["due_day"] is None
    assert len(_entries(db_session, body["id"])) == 1


def test_post_abierta_una_entry_sin_fecha(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_abierta(institution_id=1), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["institution_id"] is None  # se ignora en deuda_abierta
    assert body["first_due_date"] is None
    entries = _entries(db_session, body["id"], source_type="deuda_abierta")
    assert len(entries) == 1
    assert entries[0].event_date is None


def test_post_con_findings_no_materializa(client, db_session, catalog):
    headers = _auth(client)
    # overdue < financing → finding overdue_lower_than_financing
    resp = client.post("/debts", json=_cronograma(financing_rate="45.00", overdue_rate="30.00"),
                       headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["review_findings"] == ["overdue_lower_than_financing"]
    assert body["is_ready"] is False
    assert _entries(db_session, body["id"]) == []  # no materializó


# --- POST errores ---

def test_post_kind_gasto_rechazado(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(obligation_type_id=1), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_type_invalid"


def test_post_abierta_tipo_no_informal(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_abierta(obligation_type_id=9), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_type_invalid"


def test_post_institution_otro_pais(client, db_session, catalog):
    db_session.add(Country(code="AR", name="Argentina", visible=True, vat_rate=Decimal("21.00")))
    db_session.flush()
    db_session.add(Institution(id=2, country_code="AR", name="Banco AR", visible=True))
    db_session.flush()
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(institution_id=2), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "institution_invalid"


def test_post_deuda_sin_first_due_date(client, db_session, catalog):
    headers = _auth(client)
    body = _cronograma()
    del body["first_due_date"]
    resp = client.post("/debts", json=body, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_requires_schedule_or_date"


def test_post_cronograma_sin_due_day(client, db_session, catalog):
    headers = _auth(client)
    body = _cronograma()
    del body["due_day"]
    resp = client.post("/debts", json=body, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_schedule_requires_due_day"


def test_post_installments_cero(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(total_installments=0), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "installments_invalid"


def test_post_pago_unico_con_due_day(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_pago_unico(due_day=10), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "one_time_debt_inconsistent"


def test_post_tasa_negativa(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(financing_rate="-1.00"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "rates_negative"


def test_post_abierta_con_fecha(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_abierta(first_due_date=ONE_TIME), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "open_debt_inconsistent"


def test_post_sin_token(client, db_session, catalog):
    assert client.post("/debts", json=_cronograma()).status_code == 401


# --- GET ---

def test_get_lista_ambos_kinds(client, db_session, catalog):
    headers = _auth(client)
    client.post("/debts", json=_cronograma(), headers=headers)
    client.post("/debts", json=_abierta(), headers=headers)
    resp = client.get("/debts", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["debts"]) == 2


def test_get_vacio(client, db_session, catalog):
    headers = _auth(client)
    assert client.get("/debts", headers=headers).json() == {"debts": []}


def test_get_sin_token(client, db_session, catalog):
    assert client.get("/debts").status_code == 401


def _create_cronograma(client, headers):
    return client.post("/debts", json=_cronograma(), headers=headers).json()


def test_patch_cambia_amount(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    resp = client.patch(f"/debts/{d['id']}", json={"amount": "6400.00"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["amount"] == "6400.00"


def test_patch_cambia_tasas_rematerializa(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)  # financing 45, overdue 60 → sin findings
    # bajar financing a 50 (overdue 60 >= 50 → no dispara overdue_lower; tampoco rate_above)
    resp = client.patch(f"/debts/{d['id']}", json={"financing_rate": "50.00"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["financing_rate"] == "50.00"
    assert resp.json()["is_ready"] is True
    # entries futuras con tasa efectiva 50 × 1.22 = 61.00
    assert all(e.financing_rate == Decimal("61.00") for e in _entries(db_session, d["id"]))


def test_patch_cerrar_con_findings_limpia_futuras(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)  # lista, materializó cuotas
    assert len(_entries(db_session, d["id"])) > 0
    # introducir findings: overdue < financing → is_ready false, pero las cuotas siguen
    client.patch(f"/debts/{d['id']}", json={"overdue_rate": "5.00"}, headers=headers)
    # cerrar: reviewer fuerza is_ready=true → motor limpia futuras
    resp = client.patch(f"/debts/{d['id']}", json={"is_closed": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_closed"] is True
    assert resp.json()["review_findings"] == []
    assert resp.json()["is_ready"] is True
    assert _entries(db_session, d["id"]) == []


def test_patch_cronograma_a_pago_unico(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    resp = client.patch(f"/debts/{d['id']}", json={"total_installments": None, "due_day": None},
                       headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total_installments"] is None
    assert resp.json()["due_day"] is None


def test_patch_schedule_locked_con_pagos(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    entry = _entries(db_session, d["id"])[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("6250.00")))  # real
    db_session.flush()
    resp = client.patch(f"/debts/{d['id']}", json={"total_installments": 12}, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "debt_schedule_locked"


def test_patch_amount_no_bloqueado_con_pagos(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    entry = _entries(db_session, d["id"])[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("6250.00")))
    db_session.flush()
    resp = client.patch(f"/debts/{d['id']}", json={"amount": "7000.00"}, headers=headers)
    assert resp.status_code == 200  # amount sí es editable con pagos


def test_patch_tipo_cross_kind_rechazado(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    # 1 es gasto → otro kind
    resp = client.patch(f"/debts/{d['id']}", json={"obligation_type_id": 1}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_type_invalid"


def test_patch_abierta_no_cambia_tipo(client, db_session, catalog):
    headers = _auth(client)
    d = client.post("/debts", json=_abierta(), headers=headers).json()
    resp = client.patch(f"/debts/{d['id']}", json={"obligation_type_id": 9}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_type_invalid"


def test_patch_otro_usuario_404(client, db_session, catalog):
    headers_a = _auth(client, email="a@b.com")
    d = _create_cronograma(client, headers_a)
    headers_b = _auth(client, email="b@b.com")
    resp = client.patch(f"/debts/{d['id']}", json={"amount": "1.00"}, headers=headers_b)
    assert resp.status_code == 404


def test_patch_vacio_ok(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    resp = client.patch(f"/debts/{d['id']}", json={}, headers=headers)
    assert resp.status_code == 200


# --- prioridad (slice 2) ---

def test_post_deuda_con_priority_y_regla(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(payment_rule="minimo", priority=2), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["payment_rule"] == "minimo"
    assert body["priority"] == 2


def test_post_deuda_regla_sin_priority_rechaza(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(payment_rule="total"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "payment_rule_invalid"


def test_post_deuda_default_ninguno(client, db_session, catalog):
    headers = _auth(client)
    body = client.post("/debts", json=_cronograma(), headers=headers).json()
    assert body["payment_rule"] == "ninguno"
    assert body["priority"] is None


def test_post_abierta_mensual(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_abierta(
        payment_rule="mensual", monthly_paydown_amount="2000.00", priority_open_debt=1,
    ), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["payment_rule"] == "mensual"
    assert body["monthly_paydown_amount"] == "2000.00"
    assert body["priority_open_debt"] == 1


def test_patch_deuda_payment_rule(client, db_session, catalog):
    headers = _auth(client)
    created = _create_cronograma(client, headers)
    resp = client.patch(f"/debts/{created['id']}",
                        json={"payment_rule": "minimo", "priority": 5}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["payment_rule"] == "minimo" and resp.json()["priority"] == 5
