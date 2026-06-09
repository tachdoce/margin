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
    db_session.refresh(p)
    return p


def test_delete_real(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry)
    r = client.delete(f"/cash-flow-entries/{entry.id}/payments/{p.id}", headers=headers)
    assert r.status_code == 204
    assert db_session.get(CashFlowPayment, p.id) is None


def test_delete_planned(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    p = _pay(db_session, entry, plan_id=plan.id, planned_date=date(2026, 7, 15))
    assert client.delete(f"/cash-flow-entries/{entry.id}/payments/{p.id}", headers=headers).status_code == 204


def test_delete_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    assert client.delete(f"/cash-flow-entries/{entry.id}/payments/{uuid.uuid4()}", headers=headers).status_code == 404


def test_delete_payment_of_other_entry(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry_a = _make_entry(db_session, user)
    entry_b = _make_entry(db_session, user)
    p = _pay(db_session, entry_a)
    assert client.delete(f"/cash-flow-entries/{entry_b.id}/payments/{p.id}", headers=headers).status_code == 404
