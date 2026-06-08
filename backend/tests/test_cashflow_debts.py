from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.plan import Plan
from app.models.priority_level import PriorityLevel
from app.models.user import User
from app.services.cash_flow.debts import materialize_debt

TODAY = date(2026, 6, 1)
HORIZON = date(2026, 12, 31)


@pytest.fixture
def user(db_session, seed_uy_currency):
    # seed_uy (vía seed_uy_currency) crea UY con vat_rate 22.00
    db_session.add(PriorityLevel(level=4, name="Prioritaria", description="x"))
    db_session.flush()
    db_session.add(
        ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                       description="x", default_priority_level=4, visible=True)
    )
    db_session.flush()
    u = User(country_code="UY")
    db_session.add(u)
    db_session.flush()
    return u


def _deuda(db_session, user, **overrides):
    kwargs = dict(
        user_id=user.id,
        obligation_type_id=10,
        priority_level=4,
        currency_id=1,
        amount=Decimal("5000.00"),
        is_monthly_recurring=False,
        due_day=10,
        first_due_date=date(2026, 7, 1),
        total_installments=12,
        financing_rate=Decimal("55.00"),
        overdue_rate=None,
        rates_add_vat=True,
        shift_weekends=False,
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
            .where(CashFlowEntry.source_type == "deuda", CashFlowEntry.source_id == obligation_id)
            .order_by(CashFlowEntry.event_date)
        ).scalars()
    )


def test_cronograma_materializa_cuotas(db_session, user):
    o = _deuda(db_session, user)  # first_due 2026-07-01, due_day 10, 12 cuotas
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    # cuotas con venc en jul..dic 2026 (las de 2027 caen fuera del horizonte) → 6
    assert len(entries) == 6
    for e in entries:
        assert e.is_income is False
        assert e.source_type == "deuda"
        assert e.amount == Decimal("5000.00")
        assert e.currency_id == 1
        assert e.event_date.day == 10
    assert entries[0].event_date == date(2026, 7, 10)
    assert entries[-1].event_date == date(2026, 12, 10)


def test_tasas_efectivas_con_vat(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("55.00"), overdue_rate=None, rates_add_vat=True)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    for e in _entries(db_session, o.id):
        assert e.financing_rate == Decimal("67.10")  # 55 × 1.22
        assert e.overdue_rate is None


def test_tasas_sin_vat(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("55.00"), rates_add_vat=False)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    for e in _entries(db_session, o.id):
        assert e.financing_rate == Decimal("55.00")


def test_pago_unico_una_fila(db_session, user):
    o = _deuda(db_session, user, total_installments=None, due_day=None,
               first_due_date=date(2026, 8, 15))
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 15)


def test_gate_not_ready_no_materializa(db_session, user):
    o = _deuda(db_session, user, is_ready=False)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_is_closed_borra_futuras(db_session, user):
    o = _deuda(db_session, user)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert len(_entries(db_session, o.id)) == 6
    o.is_closed = True
    db_session.flush()
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_acortar_cronograma_reconcilia(db_session, user):
    o = _deuda(db_session, user)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert len(_entries(db_session, o.id)) == 6
    o.total_installments = 3  # solo jul, ago, sep 2026
    db_session.flush()
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 3
    assert entries[-1].event_date == date(2026, 9, 10)


def test_cambio_tasas_reescribe_futuras(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("55.00"), rates_add_vat=True)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert all(e.financing_rate == Decimal("67.10") for e in _entries(db_session, o.id))
    o.financing_rate = Decimal("100.00")
    db_session.flush()
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert all(e.financing_rate == Decimal("122.00") for e in _entries(db_session, o.id))  # 100 × 1.22


def test_pago_real_stale_lanza_excepcion(db_session, user):
    o = _deuda(db_session, user)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    fut = _entries(db_session, o.id)[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=fut.id, amount=Decimal("5000.00")))  # real
    db_session.flush()
    o.is_closed = True
    db_session.flush()
    with pytest.raises(RuntimeError):
        materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)


def test_pago_planificado_stale_se_borra(db_session, user):
    o = _deuda(db_session, user)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
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
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_pasado_no_se_toca(db_session, user):
    o = _deuda(db_session, user)
    past = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 3, 10), is_income=False,
        amount=Decimal("5000.00"), currency_id=1, source_type="deuda", source_id=o.id,
        financing_rate=Decimal("40.00"),
    )
    db_session.add(past)
    db_session.flush()
    past_id = past.id
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    survivors = {e.id: e for e in _entries(db_session, o.id)}
    assert past_id in survivors
    assert survivors[past_id].financing_rate == Decimal("40.00")  # no se reescribió


def test_due_day_null_en_cronograma_lanza_excepcion(db_session, user):
    o = _deuda(db_session, user, due_day=None, total_installments=12)
    with pytest.raises(RuntimeError):
        materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)


def test_shift_weekends_corre_finde(db_session, user):
    # 2026-07-04 es sábado; con shift → lunes 2026-07-06
    o = _deuda(db_session, user, due_day=4, total_installments=1,
               first_due_date=date(2026, 7, 1), shift_weekends=True)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 7, 6)
