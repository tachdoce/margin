import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    from sqlalchemy import select
    from app.models.user import User
    return db_session.execute(select(User).order_by(User.created_at.desc())).scalars().first()


def _make_entry(db_session, user):
    entry = CashFlowEntry(
        user_id=user.id, event_date=None, is_income=False, amount=Decimal("6000.00"),
        currency_id=1, source_type="gasto", source_id=uuid.uuid4(),
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


def _pay(db_session, entry, *, amount="100.00", plan_id=None, planned_date=None):
    p = CashFlowPayment(
        cash_flow_entry_id=entry.id, amount=Decimal(amount), plan_id=plan_id, planned_date=planned_date
    )
    db_session.add(p)
    db_session.commit()
    return p


def test_list_requires_plan_id(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    assert client.get(f"/cash-flow-entries/{entry.id}/payments", headers=headers).json()["code"] == "plan_id_required"


def test_list_month_invalid(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    r = client.get(f"/cash-flow-entries/{entry.id}/payments?plan_id={plan.id}&month=2026-13-99", headers=headers)
    assert r.json()["code"] == "month_invalid"


def test_list_real_plus_this_plan_excludes_others(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    other = _make_plan(db_session, user)
    _pay(db_session, entry, amount="1.00")  # real
    _pay(db_session, entry, amount="2.00", plan_id=plan.id, planned_date=date(2026, 7, 15))  # de este plan
    _pay(db_session, entry, amount="3.00", plan_id=other.id, planned_date=date(2026, 7, 15))  # de otro plan
    rows = client.get(f"/cash-flow-entries/{entry.id}/payments?plan_id={plan.id}", headers=headers).json()
    amounts = {r["amount"] for r in rows}
    assert amounts == {"1.00", "2.00"}
    by_amount = {r["amount"]: r for r in rows}
    assert by_amount["1.00"]["is_planned"] is False
    assert by_amount["2.00"]["is_planned"] is True


def test_list_month_filter(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    _pay(db_session, entry, amount="2.00", plan_id=plan.id, planned_date=date(2026, 7, 15))  # julio
    _pay(db_session, entry, amount="3.00", plan_id=plan.id, planned_date=date(2026, 8, 1))   # agosto
    rows = client.get(f"/cash-flow-entries/{entry.id}/payments?plan_id={plan.id}&month=2026-07", headers=headers).json()
    assert {r["amount"] for r in rows} == {"2.00"}


def test_list_empty(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    assert client.get(f"/cash-flow-entries/{entry.id}/payments?plan_id={plan.id}", headers=headers).json() == []
