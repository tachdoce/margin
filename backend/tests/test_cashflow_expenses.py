from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.plan import Plan
from app.models.user import User
from app.services.cash_flow.expenses import materialize_expense

TODAY = date(2026, 6, 1)
HORIZON = date(2026, 12, 31)  # jun..dic = 7 meses


@pytest.fixture
def user(db_session, seed_uy_currency):
    db_session.add_all(
        [
        ]
    )
    db_session.flush()
    db_session.add(
        ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                       description="x", visible=True)
    )
    db_session.flush()
    u = User(country_code="UY")
    db_session.add(u)
    db_session.flush()
    return u


def _gasto(db_session, user, **overrides):
    kwargs = dict(
        user_id=user.id,
        obligation_type_id=1,
                currency_id=1,
        amount=Decimal("12000.00"),
        is_monthly_recurring=True,
        due_day=10,
        first_due_date=None,
        shift_weekends=False,
        rates_add_vat=True,
        is_closed=False,
        review_findings="[]",
        is_ready=True,
    )
    kwargs.update(overrides)
    o = Obligation(**kwargs)
    db_session.add(o)
    db_session.flush()
    return o


def _entries(db_session, obligation_id):
    return list(
        db_session.execute(
            select(CashFlowEntry)
            .where(CashFlowEntry.source_type == "gasto", CashFlowEntry.source_id == obligation_id)
            .order_by(CashFlowEntry.event_date)
        ).scalars()
    )


def test_recurrente_materializa_por_mes(db_session, user):
    o = _gasto(db_session, user, due_day=10)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 7
    for e in entries:
        assert e.is_income is False
        assert e.source_type == "gasto"
        assert e.amount == Decimal("12000.00")
        assert e.currency_id == 1
        assert e.financing_rate is None and e.overdue_rate is None
        assert e.event_date.day == 10
    assert entries[0].event_date == date(2026, 6, 10)
    assert entries[-1].event_date == date(2026, 12, 10)


def test_unico_una_sola_entry(db_session, user):
    o = _gasto(db_session, user, is_monthly_recurring=False, due_day=None,
               first_due_date=date(2026, 8, 15))
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 15)


def test_gate_not_ready_no_materializa(db_session, user):
    o = _gasto(db_session, user, is_ready=False)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_gate_not_ready_deja_existentes_intactas(db_session, user):
    o = _gasto(db_session, user)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert len(_entries(db_session, o.id)) == 7
    # ahora se "rompe" el gate y cambia el monto: no debe tocar nada
    o.is_ready = False
    o.amount = Decimal("99999.00")
    db_session.flush()
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 7
    assert all(e.amount == Decimal("12000.00") for e in entries)


def test_is_closed_borra_futuras(db_session, user):
    o = _gasto(db_session, user)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert len(_entries(db_session, o.id)) == 7
    o.is_closed = True
    db_session.flush()
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_recurrente_a_unico_reconcilia(db_session, user):
    o = _gasto(db_session, user, due_day=10)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    agosto = next(e for e in _entries(db_session, o.id) if e.event_date.month == 8)
    agosto_id = agosto.id
    # pasa a único en agosto: misma clave (2026,8) → UPDATE in place, borra los otros 6
    o.is_monthly_recurring = False
    o.due_day = None
    o.first_due_date = date(2026, 8, 15)
    db_session.flush()
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].id == agosto_id
    assert entries[0].event_date == date(2026, 8, 15)


def test_pago_real_stale_lanza_excepcion(db_session, user):
    o = _gasto(db_session, user)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    fut = _entries(db_session, o.id)[0]  # futura
    db_session.add(CashFlowPayment(cash_flow_entry_id=fut.id, amount=Decimal("5000.00")))  # plan_id=None → real
    db_session.flush()
    o.is_closed = True  # vuelve stale a todas las futuras
    db_session.flush()
    with pytest.raises(RuntimeError):
        materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)


def test_pago_planificado_stale_se_borra(db_session, user):
    o = _gasto(db_session, user)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    fut = _entries(db_session, o.id)[0]
    plan = Plan(user_id=user.id, name="P", is_default=False, is_engine_generated=False,
                selected_at=datetime.now(timezone.utc), dial_amount=Decimal("0"),
                dial_currency_id=1, goal_kind=None, goal_amount=None, goal_currency_id=None)
    db_session.add(plan)
    db_session.flush()
    db_session.add(CashFlowPayment(cash_flow_entry_id=fut.id, amount=Decimal("5000.00"), plan_id=plan.id))
    db_session.flush()
    o.is_closed = True
    db_session.flush()
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_pasado_no_se_toca(db_session, user):
    o = _gasto(db_session, user)
    # entry pasada del mismo gasto, fuera del objetivo
    past = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 3, 10), is_income=False,
        amount=Decimal("12000.00"), currency_id=1, source_type="gasto", source_id=o.id,
    )
    db_session.add(past)
    db_session.flush()
    past_id = past.id
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    ids = {e.id for e in _entries(db_session, o.id)}
    assert past_id in ids  # no se borró
    assert len(ids) == 8  # 7 futuras + 1 pasada


def test_shift_weekends_corre_finde(db_session, user):
    # 2026-06-06 es sábado; con shift → lunes 2026-06-08
    o = _gasto(db_session, user, due_day=6, shift_weekends=True)
    materialize_expense(db_session, o.id, today=TODAY, horizon=date(2026, 6, 30))
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 6, 8)


def _entries_gasto(db_session, gasto_id):
    return list(db_session.execute(
        select(CashFlowEntry)
        .where(CashFlowEntry.source_type == "gasto", CashFlowEntry.source_id == gasto_id)
        .order_by(CashFlowEntry.event_date)
    ).scalars())


def test_gasto_recurrente_incluye_mes_actual(db_session, user):
    g = _gasto(db_session, user, due_day=10)
    materialize_expense(db_session, g.id, today=date(2026, 6, 20), horizon=date(2026, 12, 31))
    entries = _entries_gasto(db_session, g.id)
    assert entries[0].event_date == date(2026, 6, 10)  # junio incluido (hoy 20 > día 10)


def test_gasto_unico_mes_actual_aunque_paso(db_session, user):
    g = _gasto(db_session, user, is_monthly_recurring=False, due_day=None, first_due_date=date(2026, 6, 3))
    materialize_expense(db_session, g.id, today=date(2026, 6, 20), horizon=date(2026, 12, 31))
    eds = [e.event_date for e in _entries_gasto(db_session, g.id)]
    assert date(2026, 6, 3) in eds
