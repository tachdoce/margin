from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.plan import Plan

FUTURE = (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture
def catalog(db_session, seed_uy_currency):
    db_session.add_all([
    ])
    db_session.flush()
    db_session.add_all([
        ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                       description="x", visible=True),
        ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                       description="x", visible=True),
        ObligationType(id=8, obligation_kind="deuda_abierta", code="informal", name="Informal",
                       description="x", visible=True),
    ])
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _crear_gasto(client, headers):
    body = {
        "obligation_type_id": 1, "description": "Alquiler depto",
        "is_monthly_recurring": True, "due_day": 10, "currency_id": 1, "amount": "32000.00",
    }
    return client.post("/expenses", json=body, headers=headers).json()


def _crear_abierta(client, headers):
    body = {
        "obligation_type_id": 8, "description": "Le debo a mi viejo",
        "currency_id": 1, "amount": "50000.00",
    }
    return client.post("/debts", json=body, headers=headers).json()


def _crear_deuda_con_findings(client, headers):
    # overdue < financing → finding overdue_lower_than_financing → is_ready false, sin entries
    body = {
        "obligation_type_id": 10, "description": "Préstamo tasas raras",
        "due_day": 10, "currency_id": 1, "amount": "6250.00", "total_installments": 24,
        "first_due_date": FUTURE, "financing_rate": "45.00", "overdue_rate": "30.00",
    }
    return client.post("/debts", json=body, headers=headers).json()


def _obligation(db_session, obligation_id):
    return db_session.get(Obligation, obligation_id)


def _entries(db_session, obligation_id):
    return list(db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_id == obligation_id)
    ).scalars())


# --- DELETE ---

def test_delete_gasto_ok(client, db_session, catalog):
    headers = _auth(client)
    g = _crear_gasto(client, headers)
    assert len(_entries(db_session, g["id"])) > 0
    resp = client.delete(f"/obligations/{g['id']}", headers=headers)
    assert resp.status_code == 204
    assert _obligation(db_session, g["id"]) is None
    assert _entries(db_session, g["id"]) == []


def test_delete_abierta_ok(client, db_session, catalog):
    headers = _auth(client)
    d = _crear_abierta(client, headers)
    resp = client.delete(f"/obligations/{d['id']}", headers=headers)
    assert resp.status_code == 204
    assert _obligation(db_session, d["id"]) is None


def test_delete_not_found(client, db_session, catalog):
    headers = _auth(client)
    import uuid
    resp = client.delete(f"/obligations/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


def test_delete_otro_usuario_404(client, db_session, catalog):
    headers_a = _auth(client, email="a@b.com")
    g = _crear_gasto(client, headers_a)
    headers_b = _auth(client, email="b@b.com")
    resp = client.delete(f"/obligations/{g['id']}", headers=headers_b)
    assert resp.status_code == 404


def test_delete_con_hija(client, db_session, catalog):
    headers = _auth(client)
    parent = _crear_gasto(client, headers)
    user_id = _obligation(db_session, parent["id"]).user_id
    child = Obligation(
        user_id=user_id, obligation_type_id=10, currency_id=1,
        amount=Decimal("100.00"), is_monthly_recurring=False, shift_weekends=False,
        rates_add_vat=True, is_closed=False, review_findings="[]", is_ready=False,
        origin_obligation_id=parent["id"],
    )
    db_session.add(child)
    db_session.flush()
    resp = client.delete(f"/obligations/{parent['id']}", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "obligation_has_children"


def test_delete_con_pago_real(client, db_session, catalog):
    headers = _auth(client)
    g = _crear_gasto(client, headers)
    entry = _entries(db_session, g["id"])[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("32000.00")))  # plan_id None
    db_session.flush()
    resp = client.delete(f"/obligations/{g['id']}", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "obligation_has_payments"


def test_delete_con_pago_planificado_ok(client, db_session, catalog):
    headers = _auth(client)
    g = _crear_gasto(client, headers)
    entry = _entries(db_session, g["id"])[0]
    plan = Plan(user_id=_obligation(db_session, g["id"]).user_id, name="P", is_default=False,
                is_engine_generated=False, selected_at=datetime.now(timezone.utc), dial_amount=Decimal("0"),
                dial_currency_id=1, goal_kind=None, goal_amount=None, goal_currency_id=None)
    db_session.add(plan)
    db_session.flush()
    db_session.add(CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("100.00"), plan_id=plan.id))
    db_session.flush()
    resp = client.delete(f"/obligations/{g['id']}", headers=headers)
    assert resp.status_code == 204
    assert _obligation(db_session, g["id"]) is None


def test_delete_sin_token(client, db_session, catalog):
    import uuid
    assert client.delete(f"/obligations/{uuid.uuid4()}").status_code == 401


def test_acknowledge_materializa_lo_frenado(client, db_session, catalog):
    headers = _auth(client)
    d = _crear_deuda_con_findings(client, headers)
    assert d["is_ready"] is False
    assert d["review_findings"] == ["overdue_lower_than_financing"]
    assert _entries(db_session, d["id"]) == []  # findings frenaron al motor
    updated_before = _obligation(db_session, d["id"]).updated_at
    resp = client.post(f"/obligations/{d['id']}/acknowledge", json={}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_findings"] == []
    assert body["is_ready"] is True
    assert len(_entries(db_session, d["id"])) > 0  # ahora sí materializó
    # updated_at no cambió (reconocer no es cambio de negocio)
    assert _obligation(db_session, d["id"]).updated_at == updated_before


def test_acknowledge_sin_findings_409(client, db_session, catalog):
    headers = _auth(client)
    g = _crear_gasto(client, headers)  # gasto sin tasas → is_ready true, review_findings []
    resp = client.post(f"/obligations/{g['id']}/acknowledge", json={}, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "obligation_has_no_findings"


def test_acknowledge_not_found(client, db_session, catalog):
    headers = _auth(client)
    import uuid
    resp = client.post(f"/obligations/{uuid.uuid4()}/acknowledge", json={}, headers=headers)
    assert resp.status_code == 404


def test_acknowledge_otro_usuario_404(client, db_session, catalog):
    headers_a = _auth(client, email="a@b.com")
    d = _crear_deuda_con_findings(client, headers_a)
    headers_b = _auth(client, email="b@b.com")
    resp = client.post(f"/obligations/{d['id']}/acknowledge", json={}, headers=headers_b)
    assert resp.status_code == 404


def test_acknowledge_sin_token(client, db_session, catalog):
    import uuid
    assert client.post(f"/obligations/{uuid.uuid4()}/acknowledge", json={}).status_code == 401
