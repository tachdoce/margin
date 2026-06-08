from decimal import Decimal

from app.models.plan import Plan
from sqlalchemy import select


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_plan_sin_objetivo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    resp = client.post("/plans", json={"name": "Escenario sin préstamo", "dial_amount": "15000.00"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Escenario sin préstamo"
    assert body["is_default"] is False
    assert body["is_engine_generated"] is False
    assert body["dial_amount"] == "15000.00"
    assert body["dial_currency_id"] == 1
    assert body["goal_kind"] is None
    assert body["goal_amount"] is None
    assert body["goal_currency_id"] is None


def test_create_plan_con_objetivo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    resp = client.post(
        "/plans",
        json={"name": "Comprar auto", "dial_amount": "12000.00", "goal_kind": "ahorro_total", "goal_amount": "300000.00"},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["goal_kind"] == "ahorro_total"
    assert body["goal_amount"] == "300000.00"
    assert body["goal_currency_id"] == 1


def test_create_plan_select_on_create_queda_activo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    created = client.post(
        "/plans", json={"name": "Activo ya", "dial_amount": "10000.00", "select_on_create": True}, headers=headers
    ).json()
    listed = client.get("/plans", headers=headers).json()
    assert listed[0]["id"] == created["id"]  # el más nuevo selected_at queda primero


def test_create_plan_sin_select_no_queda_activo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    client.post("/plans", json={"name": "Inactivo", "dial_amount": "10000.00"}, headers=headers)
    listed = client.get("/plans", headers=headers).json()
    assert listed[0]["is_default"] is True  # el default sigue siendo el activo


def test_create_plan_name_required(client, db_session, seed_uy_currency):
    headers = _auth(client)
    resp = client.post("/plans", json={"name": "   ", "dial_amount": "10000.00"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "name_required"


def test_create_plan_dial_negativo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    resp = client.post("/plans", json={"name": "X", "dial_amount": "-1.00"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "dial_amount_invalid"


def test_create_plan_objetivo_a_medias(client, db_session, seed_uy_currency):
    headers = _auth(client)
    resp = client.post(
        "/plans", json={"name": "X", "dial_amount": "10000.00", "goal_kind": "ahorro_total"}, headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "goal_invalid"


def test_create_plan_requires_auth(client, db_session, seed_uy_currency):
    resp = client.post("/plans", json={"name": "X", "dial_amount": "10000.00"})
    assert resp.status_code == 401


def test_list_plans_incluye_default(client, db_session, seed_uy_currency):
    headers = _auth(client)
    listed = client.get("/plans", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["is_default"] is True


def test_list_plans_requires_auth(client, db_session, seed_uy_currency):
    assert client.get("/plans").status_code == 401


def _create(client, headers, **over):
    body = {"name": "Escenario", "dial_amount": "12000.00"}
    body.update(over)
    return client.post("/plans", json=body, headers=headers).json()


def test_patch_renombra_y_dial(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    resp = client.patch(f"/plans/{plan['id']}", json={"name": "Nuevo", "dial_amount": "13500.00"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Nuevo"
    assert resp.json()["dial_amount"] == "13500.00"


def test_patch_fija_objetivo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    resp = client.patch(
        f"/plans/{plan['id']}", json={"goal_kind": "ahorro_total", "goal_amount": "500000.00"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["goal_kind"] == "ahorro_total"
    assert resp.json()["goal_currency_id"] == 1


def test_patch_quita_objetivo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers, goal_kind="ahorro_total", goal_amount="500000.00")
    resp = client.patch(f"/plans/{plan['id']}", json={"goal_kind": None, "goal_amount": None}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["goal_kind"] is None and body["goal_amount"] is None and body["goal_currency_id"] is None


def test_patch_objetivo_a_medias(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    resp = client.patch(f"/plans/{plan['id']}", json={"goal_amount": "500000.00"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "goal_invalid"


def test_patch_empty(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    resp = client.patch(f"/plans/{plan['id']}", json={}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "empty_patch"


def test_patch_name_vacio(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    resp = client.patch(f"/plans/{plan['id']}", json={"name": "  "}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "name_required"


def test_patch_other_user_not_found(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan = _create(client, owner)
    other = _auth(client, email="other@b.com")
    resp = client.patch(f"/plans/{plan['id']}", json={"name": "X"}, headers=other)
    assert resp.status_code == 404


def test_select_mueve_al_primero(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)  # nace inactivo (default primero)
    assert client.get("/plans", headers=headers).json()[0]["is_default"] is True
    resp = client.post(f"/plans/{plan['id']}/select", headers=headers)
    assert resp.status_code == 200
    assert client.get("/plans", headers=headers).json()[0]["id"] == plan["id"]


def test_select_no_toca_updated_at(client, db_session, seed_uy_currency):
    import uuid as _uuid

    headers = _auth(client)
    plan = _create(client, headers)
    before = db_session.execute(select(Plan).where(Plan.id == _uuid.UUID(plan["id"]))).scalar_one().updated_at
    client.post(f"/plans/{plan['id']}/select", headers=headers)
    db_session.expire_all()
    after = db_session.execute(select(Plan).where(Plan.id == _uuid.UUID(plan["id"]))).scalar_one().updated_at
    assert before == after


def test_select_other_user_not_found(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan = _create(client, owner)
    other = _auth(client, email="other@b.com")
    assert client.post(f"/plans/{plan['id']}/select", headers=other).status_code == 404


def test_delete_default_409(client, db_session, seed_uy_currency):
    headers = _auth(client)
    default_id = client.get("/plans", headers=headers).json()[0]["id"]
    resp = client.delete(f"/plans/{default_id}", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "default_plan_undeletable"


def test_delete_no_default_borra(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    assert client.delete(f"/plans/{plan['id']}", headers=headers).status_code == 204
    ids = [p["id"] for p in client.get("/plans", headers=headers).json()]
    assert plan["id"] not in ids


def test_delete_barre_movimientos_entries_y_pagos(client, db_session, seed_uy_currency):
    import uuid as _uuid

    from app.models.cash_flow_entry import CashFlowEntry
    from app.models.cash_flow_payment import CashFlowPayment
    from app.models.plan_movement import PlanMovement

    headers = _auth(client)
    plan = _create(client, headers)
    plan_uuid = _uuid.UUID(plan["id"])

    # sembrar a mano un plan_movement + una cash_flow_entry de plan + un pago planificado del plan
    mov = PlanMovement(
        plan_id=plan_uuid, kind="deuda_informal", currency_id=1, principal_amount=Decimal("30000.00"),
        start_date=__import__("datetime").date(2026, 8, 10), rates_add_vat=True,
    )
    db_session.add(mov)
    db_session.flush()
    entry = CashFlowEntry(
        user_id=db_session.execute(select(Plan).where(Plan.id == plan_uuid)).scalar_one().user_id,
        event_date=__import__("datetime").date(2026, 8, 10), is_income=False, amount=Decimal("30000.00"),
        currency_id=1, source_type="plan_movimiento", source_id=mov.id,
    )
    db_session.add(entry)
    db_session.flush()
    db_session.add(
        CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("1000.00"), plan_id=plan_uuid,
                        planned_date=__import__("datetime").date(2026, 8, 10))
    )
    db_session.flush()

    assert client.delete(f"/plans/{plan['id']}", headers=headers).status_code == 204

    db_session.expire_all()
    assert db_session.execute(select(PlanMovement).where(PlanMovement.plan_id == plan_uuid)).first() is None
    assert db_session.execute(select(CashFlowEntry).where(CashFlowEntry.source_id == mov.id)).first() is None
    assert db_session.execute(select(CashFlowPayment).where(CashFlowPayment.plan_id == plan_uuid)).first() is None


def test_delete_other_user_not_found(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan = _create(client, owner)
    other = _auth(client, email="other@b.com")
    assert client.delete(f"/plans/{plan['id']}", headers=other).status_code == 404
