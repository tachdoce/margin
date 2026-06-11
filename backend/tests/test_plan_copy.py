import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    return db_session.execute(select(User).order_by(User.created_at.desc())).scalars().first()


def _source_plan(client, headers, **over):
    body = {"name": "Origen", "dial_amount": "12000.00"}
    body.update(over)
    return client.post("/plans", json=body, headers=headers).json()


def test_copy_plan_copies_metadata_not_selected(client, db_session, seed_uy_currency):
    headers = _headers(client)
    source = _source_plan(client, headers, goal_kind="ahorro_total", goal_amount="300000.00")
    resp = client.post(f"/plans/{source['id']}/copy", json={"name": "Copia"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] != source["id"]
    assert body["name"] == "Copia"
    assert body["is_default"] is False
    assert body["is_engine_generated"] is False
    assert body["dial_amount"] == "12000.00"
    assert body["goal_kind"] == "ahorro_total"
    assert body["goal_amount"] == "300000.00"
    assert body["goal_currency_id"] == 1
    listed = client.get("/plans", headers=headers).json()
    assert listed[0]["is_default"] is True


def test_copy_plan_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    resp = client.post(f"/plans/{uuid.uuid4()}/copy", json={"name": "Copia"}, headers=headers)
    assert resp.status_code == 404


def test_copy_plan_of_other_user(client, db_session, seed_uy_currency):
    headers_a = _headers(client, email="a@b.com")
    source = _source_plan(client, headers_a)
    headers_b = _headers(client, email="b@b.com")
    resp = client.post(f"/plans/{source['id']}/copy", json={"name": "Copia"}, headers=headers_b)
    assert resp.status_code == 404


def test_copy_plan_name_required(client, db_session, seed_uy_currency):
    headers = _headers(client)
    source = _source_plan(client, headers)
    resp = client.post(f"/plans/{source['id']}/copy", json={"name": "   "}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "name_required"


def test_copy_plan_copies_non_auto_movements_and_materializes(client, db_session, seed_uy_currency):
    headers = _headers(client)
    source = _source_plan(client, headers)
    # movement manual vía endpoint (se materializa)
    client.post(
        f"/plans/{source['id']}/movements",
        json={"kind": "deuda_informal", "currency_id": 1, "principal_amount": "30000.00", "start_date": "2026-08-10"},
        headers=headers,
    )
    copy = client.post(f"/plans/{source['id']}/copy", json={"name": "Copia"}, headers=headers).json()
    new_movements = db_session.execute(
        select(PlanMovement).where(PlanMovement.plan_id == uuid.UUID(copy["id"]))
    ).scalars().all()
    assert len(new_movements) == 1
    nm = new_movements[0]
    assert nm.kind == "deuda_informal"
    assert nm.principal_amount == Decimal("30000.00")
    assert nm.is_auto_generated is False
    entries = db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_id == nm.id)
    ).scalars().all()
    assert len(entries) >= 1


def test_copy_plan_excludes_auto_movements(client, db_session, seed_uy_currency):
    headers = _headers(client)
    source = _source_plan(client, headers)
    db_session.add(PlanMovement(
        plan_id=uuid.UUID(source["id"]), kind="ingreso", currency_id=1,
        principal_amount=Decimal("45000.00"), start_date=date(2026, 7, 5),
        rates_add_vat=False, is_auto_generated=True,
    ))
    db_session.commit()
    copy = client.post(f"/plans/{source['id']}/copy", json={"name": "Copia"}, headers=headers).json()
    new_movements = db_session.execute(
        select(PlanMovement).where(PlanMovement.plan_id == uuid.UUID(copy["id"]))
    ).scalars().all()
    assert new_movements == []


def test_copy_plan_payment_against_shared_entry_keeps_entry(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    source = _source_plan(client, headers)
    shared = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 7, 1), is_income=False, amount=Decimal("5000.00"),
        currency_id=1, source_type="gasto", source_id=uuid.uuid4(),
    )
    db_session.add(shared)
    db_session.commit()
    db_session.refresh(shared)
    client.post(
        f"/cash-flow-entries/{shared.id}/payments",
        json={"amount": "1000.00", "plan_id": source["id"], "planned_date": "2026-07-01"},
        headers=headers,
    )
    copy = client.post(f"/plans/{source['id']}/copy", json={"name": "Copia"}, headers=headers).json()
    new_payments = db_session.execute(
        select(CashFlowPayment).where(CashFlowPayment.plan_id == uuid.UUID(copy["id"]))
    ).scalars().all()
    assert len(new_payments) == 1
    assert new_payments[0].cash_flow_entry_id == shared.id
    assert new_payments[0].amount == Decimal("1000.00")


def test_copy_plan_payment_against_own_movement_rebinds(client, db_session, seed_uy_currency):
    headers = _headers(client)
    source = _source_plan(client, headers)
    mv = client.post(
        f"/plans/{source['id']}/movements",
        json={"kind": "deuda_informal", "currency_id": 1, "principal_amount": "30000.00", "start_date": "2026-08-10"},
        headers=headers,
    ).json()
    src_entry = db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_id == uuid.UUID(mv["id"]))
    ).scalars().first()
    client.post(
        f"/cash-flow-entries/{src_entry.id}/payments",
        json={"amount": "2000.00", "plan_id": source["id"], "planned_date": "2026-08-10"},
        headers=headers,
    )
    copy = client.post(f"/plans/{source['id']}/copy", json={"name": "Copia"}, headers=headers).json()
    new_mv = db_session.execute(
        select(PlanMovement).where(PlanMovement.plan_id == uuid.UUID(copy["id"]))
    ).scalars().first()
    new_entry = db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_id == new_mv.id)
    ).scalars().first()
    new_payment = db_session.execute(
        select(CashFlowPayment).where(CashFlowPayment.plan_id == uuid.UUID(copy["id"]))
    ).scalars().first()
    assert new_payment is not None
    assert new_payment.cash_flow_entry_id == new_entry.id
    assert new_payment.cash_flow_entry_id != src_entry.id
    assert new_entry.source_id == new_mv.id


def test_copy_plan_discards_payment_against_auto_movement(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    source = _source_plan(client, headers)
    auto_mv = PlanMovement(
        plan_id=uuid.UUID(source["id"]), kind="deuda_informal", currency_id=1,
        principal_amount=Decimal("30000.00"), start_date=date(2026, 8, 10),
        rates_add_vat=False, is_auto_generated=True,
    )
    db_session.add(auto_mv)
    db_session.commit()
    db_session.refresh(auto_mv)
    auto_entry = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 8, 10), is_income=False, amount=Decimal("30000.00"),
        currency_id=1, source_type="plan_movimiento", source_id=auto_mv.id,
    )
    db_session.add(auto_entry)
    db_session.commit()
    db_session.refresh(auto_entry)
    db_session.add(CashFlowPayment(
        cash_flow_entry_id=auto_entry.id, amount=Decimal("2000.00"),
        plan_id=uuid.UUID(source["id"]), planned_date=date(2026, 8, 10), is_auto_generated=False,
    ))
    db_session.commit()
    copy = client.post(f"/plans/{source['id']}/copy", json={"name": "Copia"}, headers=headers).json()
    new_payments = db_session.execute(
        select(CashFlowPayment).where(CashFlowPayment.plan_id == uuid.UUID(copy["id"]))
    ).scalars().all()
    assert new_payments == []


def test_copy_plan_ignores_real_payments(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    source = _source_plan(client, headers)
    shared = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 7, 1), is_income=False, amount=Decimal("5000.00"),
        currency_id=1, source_type="gasto", source_id=uuid.uuid4(),
    )
    db_session.add(shared)
    db_session.commit()
    db_session.refresh(shared)
    client.post(f"/cash-flow-entries/{shared.id}/payments", json={"amount": "1000.00"}, headers=headers)
    copy = client.post(f"/plans/{source['id']}/copy", json={"name": "Copia"}, headers=headers).json()
    new_payments = db_session.execute(
        select(CashFlowPayment).where(CashFlowPayment.plan_id == uuid.UUID(copy["id"]))
    ).scalars().all()
    assert new_payments == []
