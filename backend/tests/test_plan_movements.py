import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.plan_movement import PlanMovement


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _plan(client, headers, **over):
    body = {"name": "Escenario", "dial_amount": "12000.00"}
    body.update(over)
    return client.post("/plans", json=body, headers=headers).json()["id"]


def _default_plan_id(client, headers):
    plans = client.get("/plans", headers=headers).json()
    return next(p["id"] for p in plans if p["is_default"])


def _ingreso(**over):
    body = {"kind": "ingreso", "currency_id": 1, "principal_amount": "45000.00", "start_date": "2026-07-05"}
    body.update(over)
    return body


def _prestamo(**over):
    body = {
        "kind": "prestamo",
        "currency_id": 1,
        "principal_amount": "200000.00",
        "start_date": "2026-07-01",
        "installment_amount": "10500.00",
        "installment_start_date": "2026-08-01",
        "total_installments": 24,
        "financing_rate": "72.00",
        "overdue_rate": "85.00",
        "rates_add_vat": True,
    }
    body.update(over)
    return body


def test_create_ingreso(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_ingreso(income_duration_months=None), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "ingreso"
    assert body["installment_amount"] is None
    assert body["principal_amount"] == "45000.00"


def test_create_deuda_informal(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(
        f"/plans/{plan_id}/movements",
        json={"kind": "deuda_informal", "currency_id": 1, "principal_amount": "30000.00", "start_date": "2026-08-10"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "deuda_informal"


def test_create_prestamo_fija_income_duration_1(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_prestamo(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "prestamo"
    assert body["income_duration_months"] == 1
    assert body["total_installments"] == 24


def test_create_materializa_entries(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    movement = client.post(f"/plans/{plan_id}/movements", json=_prestamo(), headers=headers).json()
    entries = db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_id == uuid.UUID(movement["id"]))
    ).scalars().all()
    assert len(entries) >= 1  # la entrada + cuotas futuras


def test_create_default_plan_409(client, db_session, seed_uy_currency):
    headers = _auth(client)
    default_id = _default_plan_id(client, headers)
    resp = client.post(f"/plans/{default_id}/movements", json=_ingreso(), headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "default_plan_no_movements"


def test_create_kind_invalid(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_ingreso(kind="otro"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "kind_invalid"


def test_create_principal_invalido(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_ingreso(principal_amount="0.00"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "amount_invalid"


def test_create_campo_de_otro_kind(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    # ingreso con un campo de cuotas -> movement_fields_invalid
    resp = client.post(
        f"/plans/{plan_id}/movements", json=_ingreso(installment_amount="100.00"), headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "movement_fields_invalid"


def test_create_prestamo_sin_total_installments(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    body = _prestamo()
    del body["total_installments"]
    resp = client.post(f"/plans/{plan_id}/movements", json=body, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "installments_invalid"


def test_create_currency_no_disponible(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_ingreso(currency_id=999), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "currency_not_available"


def test_create_other_user_404(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan_id = _plan(client, owner)
    other = _auth(client, email="other@b.com")
    resp = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=other)
    assert resp.status_code == 404


def test_create_requires_auth(client, db_session, seed_uy_currency):
    assert client.post("/plans/00000000-0000-0000-0000-000000000000/movements", json=_ingreso()).status_code == 401


def test_list_movements_ordenado(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    client.post(f"/plans/{plan_id}/movements", json=_ingreso(start_date="2026-09-05"), headers=headers)
    client.post(f"/plans/{plan_id}/movements", json=_ingreso(start_date="2026-07-05"), headers=headers)
    listed = client.get(f"/plans/{plan_id}/movements", headers=headers).json()
    assert [m["start_date"] for m in listed] == ["2026-07-05", "2026-09-05"]


def test_list_default_vacio(client, db_session, seed_uy_currency):
    headers = _auth(client)
    default_id = _default_plan_id(client, headers)
    assert client.get(f"/plans/{default_id}/movements", headers=headers).json() == []


def test_list_other_user_404(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan_id = _plan(client, owner)
    other = _auth(client, email="other@b.com")
    assert client.get(f"/plans/{plan_id}/movements", headers=other).status_code == 404


def _create_prestamo(client, headers, plan_id):
    return client.post(f"/plans/{plan_id}/movements", json=_prestamo(), headers=headers).json()


def test_patch_edita_principal(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=headers).json()
    resp = client.patch(
        f"/plans/{plan_id}/movements/{mov['id']}", json={"principal_amount": "50000.00"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["principal_amount"] == "50000.00"


def test_patch_ajusta_cuota_rematerializa(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = _create_prestamo(client, headers, plan_id)
    resp = client.patch(
        f"/plans/{plan_id}/movements/{mov['id']}", json={"installment_amount": "11000.00"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["installment_amount"] == "11000.00"
    cuotas = db_session.execute(
        select(CashFlowEntry).where(
            CashFlowEntry.source_id == uuid.UUID(mov["id"]), CashFlowEntry.source_type == "plan_movimiento"
        )
    ).scalars().all()
    assert all(c.amount == Decimal("11000.00") for c in cuotas)


def test_patch_ignora_kind(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=headers).json()
    resp = client.patch(
        f"/plans/{plan_id}/movements/{mov['id']}", json={"kind": "prestamo", "description": "x"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "ingreso"  # no cambió


def test_patch_campo_de_otro_kind(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=headers).json()
    resp = client.patch(
        f"/plans/{plan_id}/movements/{mov['id']}", json={"installment_amount": "100.00"}, headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "movement_fields_invalid"


def test_patch_empty(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=headers).json()
    resp = client.patch(f"/plans/{plan_id}/movements/{mov['id']}", json={}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "empty_patch"


def test_patch_other_user_404(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan_id = _plan(client, owner)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=owner).json()
    other = _auth(client, email="other@b.com")
    resp = client.patch(f"/plans/{plan_id}/movements/{mov['id']}", json={"description": "x"}, headers=other)
    assert resp.status_code == 404


def test_delete_borra_movimiento_y_entries(client, db_session, seed_uy_currency):
    from app.models.cash_flow_payment import CashFlowPayment
    from app.models.plan_movement import PlanMovement

    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = _create_prestamo(client, headers, plan_id)
    mov_uuid = uuid.UUID(mov["id"])

    # imputar un pago planificado a una entry del movimiento
    entry = db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_id == mov_uuid)
    ).scalars().first()
    db_session.add(
        CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("100.00"), plan_id=uuid.UUID(plan_id),
                        planned_date=entry.event_date)
    )
    db_session.flush()

    assert client.delete(f"/plans/{plan_id}/movements/{mov['id']}", headers=headers).status_code == 204

    db_session.expire_all()
    assert db_session.get(PlanMovement, mov_uuid) is None
    assert db_session.execute(select(CashFlowEntry).where(CashFlowEntry.source_id == mov_uuid)).first() is None
    assert db_session.execute(
        select(CashFlowPayment).where(CashFlowPayment.cash_flow_entry_id == entry.id)
    ).first() is None


def test_delete_missing_404(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.delete(
        f"/plans/{plan_id}/movements/00000000-0000-0000-0000-000000000000", headers=headers
    )
    assert resp.status_code == 404


def test_delete_other_user_404(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan_id = _plan(client, owner)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=owner).json()
    other = _auth(client, email="other@b.com")
    assert client.delete(f"/plans/{plan_id}/movements/{mov['id']}", headers=other).status_code == 404


def test_create_movement_defaults_auto_generated_false(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    movement = client.post(f"/plans/{plan_id}/movements", json=_ingreso(income_duration_months=None), headers=headers).json()
    pm = db_session.get(PlanMovement, uuid.UUID(movement["id"]))
    assert pm.is_auto_generated is False


def test_plan_movement_auto_generated_persists_true(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    pm = PlanMovement(
        plan_id=uuid.UUID(plan_id), kind="ingreso", currency_id=1,
        principal_amount=Decimal("1000.00"), start_date=date(2026, 7, 1),
        rates_add_vat=False, is_auto_generated=True,
    )
    db_session.add(pm)
    db_session.commit()
    db_session.refresh(pm)
    assert pm.is_auto_generated is True


def test_movement_out_exposes_auto_generated_and_create_ignores_input(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    body = _ingreso(income_duration_months=None)
    body["is_auto_generated"] = True  # intento de setearlo: debe ignorarse
    movement = client.post(f"/plans/{plan_id}/movements", json=body, headers=headers).json()
    assert movement["is_auto_generated"] is False


def test_update_movement_ignores_auto_generated(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(income_duration_months=None), headers=headers).json()
    assert mov["is_auto_generated"] is False
    resp = client.patch(
        f"/plans/{plan_id}/movements/{mov['id']}",
        json={"principal_amount": "50000.00", "is_auto_generated": True},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_auto_generated"] is False
    db_session.expire_all()
    assert db_session.get(PlanMovement, uuid.UUID(mov["id"])).is_auto_generated is False
