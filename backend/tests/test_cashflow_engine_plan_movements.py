from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.currency import Currency
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.services.cash_flow.plan_movements import materialize_plan_movement


def _seed_movement(db_session, **over):
    """country UY (seed_uy, vat 22) + currency + user + plan no-default + un plan_movement."""
    db_session.add(Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True))
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    plan = Plan(
        user_id=user.id,
        name="Escenario",
        is_default=False,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("0.00"),
        dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.flush()
    fields = dict(
        plan_id=plan.id,
        kind="ingreso",
        currency_id=1,
        description=None,
        principal_amount=Decimal("45000.00"),
        start_date=date(2026, 7, 5),
        income_duration_months=None,
        installment_amount=None,
        installment_start_date=None,
        total_installments=None,
        financing_rate=None,
        overdue_rate=None,
        rates_add_vat=True,
    )
    fields.update(over)
    mov = PlanMovement(**fields)
    db_session.add(mov)
    db_session.flush()
    return mov


def _entries(db_session, mov):
    return list(
        db_session.execute(
            select(CashFlowEntry)
            .where(
                CashFlowEntry.source_id == mov.id,
                CashFlowEntry.source_type.in_(("plan_movimiento", "plan_movimiento_entrada")),
            )
            .order_by(CashFlowEntry.event_date, CashFlowEntry.source_type)
        ).scalars()
    )


def test_ingreso_unico(db_session, seed_uy):
    mov = _seed_movement(db_session, kind="ingreso", income_duration_months=1, start_date=date(2026, 8, 10))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, mov)
    assert len(entries) == 1
    e = entries[0]
    assert e.event_date == date(2026, 8, 10)
    assert e.is_income is True
    assert e.source_type == "plan_movimiento"
    assert e.amount == Decimal("45000.00")
    assert e.financing_rate is None and e.overdue_rate is None


def test_ingreso_limitado(db_session, seed_uy):
    mov = _seed_movement(db_session, kind="ingreso", income_duration_months=3, start_date=date(2026, 8, 10))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, mov)
    assert [e.event_date for e in entries] == [date(2026, 8, 10), date(2026, 9, 10), date(2026, 10, 10)]


def test_ingreso_recurrente(db_session, seed_uy):
    mov = _seed_movement(db_session, kind="ingreso", income_duration_months=None, start_date=date(2026, 7, 5))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    entries = _entries(db_session, mov)
    assert len(entries) == 6  # jul..dic
    assert all(e.is_income is True and e.source_type == "plan_movimiento" for e in entries)


def test_deuda_informal(db_session, seed_uy):
    mov = _seed_movement(
        db_session, kind="deuda_informal", principal_amount=Decimal("30000.00"), start_date=date(2026, 8, 10)
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, mov)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 10)
    assert entries[0].is_income is False
    assert entries[0].source_type == "plan_movimiento"


def test_prestamo_entrada_y_cuotas(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 8, 1),
        total_installments=3,
        financing_rate=None,
        overdue_rate=None,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, mov)
    entradas = [e for e in entries if e.source_type == "plan_movimiento_entrada"]
    cuotas = [e for e in entries if e.source_type == "plan_movimiento"]
    assert len(entradas) == 1
    assert entradas[0].is_income is True
    assert entradas[0].event_date == date(2026, 7, 1)
    assert entradas[0].amount == Decimal("200000.00")
    assert len(cuotas) == 3
    assert all(c.is_income is False and c.amount == Decimal("10500.00") for c in cuotas)
    # 2026-08-01 es sábado -> la cuota (vencimiento real) corre al lunes 2026-08-03; sep/oct caen en día hábil
    assert [c.event_date for c in cuotas] == [date(2026, 8, 3), date(2026, 9, 1), date(2026, 10, 1)]


def test_convivencia_entrada_y_primera_cuota_mismo_mes(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 7, 1),  # mismo mes que start_date
        total_installments=2,
        financing_rate=None,
        overdue_rate=None,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    julio = [e for e in _entries(db_session, mov) if e.event_date.month == 7 and e.event_date.year == 2026]
    assert len(julio) == 2
    assert {e.source_type for e in julio} == {"plan_movimiento", "plan_movimiento_entrada"}


def test_tasa_efectiva_con_iva(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 8, 1),
        total_installments=1,
        financing_rate=Decimal("72.00"),
        overdue_rate=Decimal("85.00"),
        rates_add_vat=True,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    cuota = [e for e in _entries(db_session, mov) if e.source_type == "plan_movimiento"][0]
    assert cuota.financing_rate == Decimal("87.84")  # 72.00 * 1.22
    assert cuota.overdue_rate == Decimal("103.70")  # 85.00 * 1.22


def test_tasa_sin_iva_queda_literal(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 8, 1),
        total_installments=1,
        financing_rate=Decimal("72.00"),
        overdue_rate=None,
        rates_add_vat=False,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    cuota = [e for e in _entries(db_session, mov) if e.source_type == "plan_movimiento"][0]
    assert cuota.financing_rate == Decimal("72.00")
    assert cuota.overdue_rate is None


def test_cuota_corre_por_finde(db_session, seed_uy):
    # 2026-08-15 es sábado; la cuota (vencimiento) corre al lunes 2026-08-17
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 8, 15),
        total_installments=1,
        financing_rate=None,
        overdue_rate=None,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    cuota = [e for e in _entries(db_session, mov) if e.source_type == "plan_movimiento"][0]
    assert cuota.event_date == date(2026, 8, 17)


def test_ingreso_no_corre_por_finde(db_session, seed_uy):
    # 2026-08-15 es sábado; el ingreso NO corre (queda literal)
    mov = _seed_movement(
        db_session, kind="ingreso", income_duration_months=None, start_date=date(2026, 8, 15)
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 8, 1), horizon=date(2026, 8, 31))

    entries = _entries(db_session, mov)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 15)


def test_no_modela_el_pasado(db_session, seed_uy):
    mov = _seed_movement(db_session, kind="ingreso", income_duration_months=1, start_date=date(2026, 1, 10))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    assert _entries(db_session, mov) == []


def test_idempotencia(db_session, seed_uy):
    mov = _seed_movement(db_session, kind="ingreso", income_duration_months=None, start_date=date(2026, 7, 5))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    assert len(_entries(db_session, mov)) == 6


def test_reconciliacion_achicar_cuotas(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 8, 1),
        total_installments=4,
        financing_rate=None,
        overdue_rate=None,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))
    cuotas = [e for e in _entries(db_session, mov) if e.source_type == "plan_movimiento"]
    assert len(cuotas) == 4

    mov.total_installments = 2
    db_session.flush()
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    cuotas = [e for e in _entries(db_session, mov) if e.source_type == "plan_movimiento"]
    # 2026-08-01 es sábado -> corre al lunes 2026-08-03; sep cae en día hábil
    assert [c.event_date for c in cuotas] == [date(2026, 8, 3), date(2026, 9, 1)]
