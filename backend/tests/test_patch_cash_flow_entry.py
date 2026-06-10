import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.user import User

TODAY = date.today()
MONTH_START = TODAY.replace(day=1)
PAST = MONTH_START - timedelta(days=1)
FUTURE = MONTH_START + timedelta(days=45)


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    return db_session.execute(select(User)).scalars().all()[-1]


def _seed_types(db_session):
    db_session.merge(PriorityLevel(level=2, name="Esencial", description="x"))
    db_session.flush()
    db_session.merge(ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                                    description="x", default_priority_level=2, visible=True))
    db_session.commit()


def _obligation(db_session, user):
    o = Obligation(
        user_id=user.id, obligation_type_id=1, priority_level=2, description="Luz",
        is_monthly_recurring=True, currency_id=1, amount=Decimal("3000.00"), shift_weekends=False,
        rates_add_vat=False, is_closed=False, review_findings="[]", is_ready=True,
    )
    db_session.add(o)
    db_session.commit()
    db_session.refresh(o)
    return o


def _entry(db_session, user, *, source_id, event_date, amount="3000.00", source_type="gasto"):
    e = CashFlowEntry(
        user_id=user.id, event_date=event_date, is_income=False, amount=Decimal(amount),
        currency_id=1, source_type=source_type, source_id=source_id,
    )
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    return e


def test_patch_amount_ok(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    e = _entry(db_session, user, source_id=o.id, event_date=FUTURE, amount="3000.00")
    r = client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "6000.00"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["amount"] == "6000.00"
    assert set(r.json().keys()) == {"id", "event_date", "amount", "currency_id", "source_type"}


def test_patch_current_month_ok(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    e = _entry(db_session, user, source_id=o.id, event_date=MONTH_START, amount="3000.00")
    assert client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "1.00"}, headers=headers).status_code == 200


def test_patch_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    assert client.patch(f"/cash-flow-entries/{uuid.uuid4()}", json={"amount": "1.00"}, headers=headers).status_code == 404


def test_patch_credit_card_now_editable(client, db_session, seed_uy_currency):
    # con todos los tipos editables, una entry de tarjeta también se edita por PATCH
    headers = _headers(client)
    user = _last_user(db_session)
    e = _entry(db_session, user, source_id=uuid.uuid4(), event_date=FUTURE, source_type="tarjeta_credito")
    r = client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "1.00"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["amount"] == "1.00"


def test_patch_past_month_not_editable(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    e = _entry(db_session, user, source_id=o.id, event_date=PAST)
    r = client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "1.00"}, headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "entry_not_editable"


def test_patch_amount_invalid(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    e = _entry(db_session, user, source_id=o.id, event_date=FUTURE)
    assert client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "0"}, headers=headers).json()["code"] == "amount_invalid"
    assert client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "-5"}, headers=headers).json()["code"] == "amount_invalid"
