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
PAST = MONTH_START - timedelta(days=1)        # último día del mes anterior
FUTURE = MONTH_START + timedelta(days=45)     # ~mes siguiente


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
    db_session.merge(ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                                    description="x", default_priority_level=2, visible=True))
    db_session.commit()


def _obligation(db_session, user, *, type_id=1):
    o = Obligation(
        user_id=user.id, obligation_type_id=type_id, priority_level=2, description="Luz",
        is_monthly_recurring=True, currency_id=1, amount=Decimal("3000.00"), shift_weekends=False,
        rates_add_vat=False, is_closed=False, review_findings="[]", is_ready=True,
    )
    db_session.add(o)
    db_session.commit()
    db_session.refresh(o)
    return o


def _entry(db_session, user, source, *, event_date, amount="3000.00", source_type="gasto"):
    e = CashFlowEntry(
        user_id=user.id, event_date=event_date, is_income=False, amount=Decimal(amount),
        currency_id=1, source_type=source_type, source_id=source.id,
    )
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    return e


def test_requires_source_id(client, db_session, seed_uy_currency):
    headers = _headers(client)
    assert client.get("/cash-flow-entries/by-source", headers=headers).json()["code"] == "source_id_required"


def test_source_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    assert client.get(f"/cash-flow-entries/by-source?source_id={uuid.uuid4()}", headers=headers).status_code == 404


def test_source_of_other_user(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers_a = _headers(client, email="a@b.com")
    user_a = _last_user(db_session)
    o = _obligation(db_session, user_a)
    headers_b = _headers(client, email="b@b.com")
    assert client.get(f"/cash-flow-entries/by-source?source_id={o.id}", headers=headers_b).status_code == 404


def test_deuda_source_now_listed(client, db_session, seed_uy_currency):
    # con todos los tipos editables, una deuda también se lista por by-source
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user, type_id=10)  # deuda
    _entry(db_session, user, o, event_date=MONTH_START, amount="2.00", source_type="deuda")
    rows = client.get(f"/cash-flow-entries/by-source?source_id={o.id}", headers=headers).json()
    assert [r["amount"] for r in rows] == ["2.00"]


def test_by_source_generic_non_obligation(client, db_session, seed_uy_currency):
    # fuente NO-obligación (ingreso): by-source resuelve por las entries, sin tabla obligations
    headers = _headers(client)
    user = _last_user(db_session)
    source_id = uuid.uuid4()
    db_session.add(CashFlowEntry(
        user_id=user.id, event_date=MONTH_START, is_income=True, amount=Decimal("45000.00"),
        currency_id=1, source_type="ingreso", source_id=source_id,
    ))
    db_session.commit()
    rows = client.get(f"/cash-flow-entries/by-source?source_id={source_id}", headers=headers).json()
    assert [r["source_type"] for r in rows] == ["ingreso"]


def test_by_source_credit_card_not_editable(client, db_session, seed_uy_currency):
    # tarjeta_credito ya no es editable
    headers = _headers(client)
    user = _last_user(db_session)
    source_id = uuid.uuid4()
    db_session.add(CashFlowEntry(
        user_id=user.id, event_date=MONTH_START, is_income=False, amount=Decimal("1000.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=source_id,
    ))
    db_session.commit()
    r = client.get(f"/cash-flow-entries/by-source?source_id={source_id}", headers=headers)
    assert r.json()["code"] == "source_not_editable"


def test_lists_current_and_future_excludes_past_ordered(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    _entry(db_session, user, o, event_date=PAST, amount="1.00")
    _entry(db_session, user, o, event_date=FUTURE, amount="2.00")
    _entry(db_session, user, o, event_date=MONTH_START, amount="3.00")
    rows = client.get(f"/cash-flow-entries/by-source?source_id={o.id}", headers=headers).json()
    assert [r["amount"] for r in rows] == ["3.00", "2.00"]  # current luego future; past excluido
    assert set(rows[0].keys()) == {"id", "event_date", "amount", "currency_id", "source_type"}


def test_empty_when_no_current_or_future(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    _entry(db_session, user, o, event_date=PAST, amount="1.00")
    assert client.get(f"/cash-flow-entries/by-source?source_id={o.id}", headers=headers).json() == []
