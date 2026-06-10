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


def _pay(db_session, entry, *, amount="100.00", note=None, plan_id=None, planned_date=None):
    p = CashFlowPayment(
        cash_flow_entry_id=entry.id, amount=Decimal(amount), note=note, plan_id=plan_id, planned_date=planned_date
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def test_patch_amount(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry, amount="100.00")
    r = client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"amount": "150.00"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["amount"] == "150.00"


def test_patch_note_to_null(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry, note="algo")
    r = client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"note": None}, headers=headers)
    assert r.status_code == 200
    assert r.json()["note"] is None


def test_patch_empty(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry)
    assert client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={}, headers=headers).json()["code"] == "empty_patch"


def test_patch_amount_invalid(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry)
    assert client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"amount": "0"}, headers=headers).json()["code"] == "amount_invalid"


def test_patch_planned_date_on_real(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry)  # real
    r = client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"planned_date": "2026-07-15"}, headers=headers)
    assert r.json()["code"] == "planned_date_on_real_payment"


def test_patch_reschedule_planned(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    p = _pay(db_session, entry, plan_id=plan.id, planned_date=date(2026, 7, 15))
    r = client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"planned_date": "2026-08-01"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["planned_date"] == "2026-08-01"


def test_patch_planned_date_null_on_planned(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    p = _pay(db_session, entry, plan_id=plan.id, planned_date=date(2026, 7, 15))
    assert client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"planned_date": None}, headers=headers).json()["code"] == "planned_date_invalid"


def test_patch_payment_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    assert client.patch(f"/cash-flow-entries/{entry.id}/payments/{uuid.uuid4()}", json={"amount": "1"}, headers=headers).status_code == 404


def test_update_payment_ignores_auto_generated(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry, amount="100.00")  # manual -> is_auto_generated False
    assert p.is_auto_generated is False
    r = client.patch(
        f"/cash-flow-entries/{entry.id}/payments/{p.id}",
        json={"amount": "150.00", "is_auto_generated": True},
        headers=headers,
    )
    assert r.status_code == 200
    db_session.expire_all()
    assert db_session.get(CashFlowPayment, p.id).is_auto_generated is False
