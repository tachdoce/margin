import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.cash_flow_entry import CashFlowEntry
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    from app.models.user import User
    return db_session.execute(__import__("sqlalchemy").select(User).order_by(User.created_at.desc())).scalars().first()


def _make_entry(db_session, user, *, source_type="gasto", source_id=None, is_income=False, amount="6000.00"):
    entry = CashFlowEntry(
        user_id=user.id,
        event_date=None,
        is_income=is_income,
        amount=Decimal(amount),
        currency_id=1,
        source_type=source_type,
        source_id=source_id or uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _make_plan(db_session, user):
    plan = Plan(
        user_id=user.id,
        name="Test plan",
        is_default=False,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("0"),
        dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _make_plan_entry(db_session, user, plan):
    pm = PlanMovement(
        plan_id=plan.id,
        kind="ingreso",
        currency_id=1,
        principal_amount=Decimal("1000.00"),
        start_date=date(2026, 1, 1),
        rates_add_vat=False,
    )
    db_session.add(pm)
    db_session.commit()
    db_session.refresh(pm)
    entry = _make_entry(db_session, user, source_type="plan_movimiento", source_id=pm.id)
    return entry


def test_create_real_payment(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "4500.00", "note": "transf"}, headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["amount"] == "4500.00"
    assert body["plan_id"] is None
    assert body["planned_date"] is None
    assert body["cash_flow_entry_id"] == str(entry.id)


def test_create_planned_payment(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    r = client.post(
        f"/cash-flow-entries/{entry.id}/payments",
        json={"amount": "5000.00", "plan_id": str(plan.id), "planned_date": "2026-07-15"},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.json()["plan_id"] == str(plan.id)
    assert r.json()["planned_date"] == "2026-07-15"


def test_create_entry_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    r = client.post(f"/cash-flow-entries/{uuid.uuid4()}/payments", json={"amount": "10.00"}, headers=headers)
    assert r.status_code == 404


def test_create_entry_of_other_user(client, db_session, seed_uy_currency):
    headers_a = _headers(client, email="a@b.com")
    user_a = _last_user(db_session)
    entry = _make_entry(db_session, user_a)
    headers_b = _headers(client, email="b@b.com")
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "10.00"}, headers=headers_b)
    assert r.status_code == 404


def test_create_plan_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    r = client.post(
        f"/cash-flow-entries/{entry.id}/payments",
        json={"amount": "10.00", "plan_id": str(uuid.uuid4()), "planned_date": "2026-07-15"},
        headers=headers,
    )
    assert r.status_code == 404


def test_create_planned_incomplete(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "10.00", "planned_date": "2026-07-15"}, headers=headers)
    assert r.json()["code"] == "planned_payment_incomplete"


def test_create_real_against_plan_entry_409(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _make_plan(db_session, user)
    entry = _make_plan_entry(db_session, user, plan)
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "10.00"}, headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "entry_not_payable"


def test_create_planned_wrong_plan_409(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    plan_a = _make_plan(db_session, user)
    plan_b = _make_plan(db_session, user)
    entry = _make_plan_entry(db_session, user, plan_a)
    r = client.post(
        f"/cash-flow-entries/{entry.id}/payments",
        json={"amount": "10.00", "plan_id": str(plan_b.id), "planned_date": "2026-07-15"},
        headers=headers,
    )
    assert r.json()["code"] == "entry_not_payable"


def test_create_planned_against_real_entry_ok(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)  # real
    plan = _make_plan(db_session, user)
    r = client.post(
        f"/cash-flow-entries/{entry.id}/payments",
        json={"amount": "10.00", "plan_id": str(plan.id), "planned_date": "2026-07-15"},
        headers=headers,
    )
    assert r.status_code == 201


def test_create_real_against_credit_card_entry_ok(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user, source_type="tarjeta_credito")
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "100.00"}, headers=headers)
    assert r.status_code == 201


def test_create_amount_invalid(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    assert client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "0"}, headers=headers).json()["code"] == "amount_invalid"
    assert client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "-5"}, headers=headers).json()["code"] == "amount_invalid"
