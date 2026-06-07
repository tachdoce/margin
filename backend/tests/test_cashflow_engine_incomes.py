from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.currency import Currency
from app.models.income import Income
from app.models.income_type import IncomeType
from app.models.user import User
from app.services.cash_flow.incomes import materialize_income


def _seed_income(db_session, **over):
    """country UY (seed_uy) + currency + income_type + user + un income recurrente por default."""
    db_session.add(Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True))
    db_session.add(IncomeType(id=1, code="sueldo", name="Sueldo", visible=True))
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    fields = dict(
        user_id=user.id,
        income_type_id=1,
        currency_id=1,
        amount=Decimal("45000.00"),
        description="Sueldo principal",
        is_monthly_recurring=True,
        payment_day=5,
        first_income_date=None,
        total_months=None,
        shift_weekends=False,
    )
    fields.update(over)
    income = Income(**fields)
    db_session.add(income)
    db_session.flush()
    return income


def _entries(db_session, income):
    return list(
        db_session.execute(
            select(CashFlowEntry)
            .where(CashFlowEntry.source_type == "ingreso", CashFlowEntry.source_id == income.id)
            .order_by(CashFlowEntry.event_date)
        ).scalars()
    )


def test_recurrente_genera_una_por_mes(db_session, seed_uy):
    income = _seed_income(db_session)
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 6  # jul..dic
    for e in entries:
        assert e.is_income is True
        assert e.source_type == "ingreso"
        assert e.source_id == income.id
        assert e.amount == Decimal("45000.00")
        assert e.currency_id == 1
        assert e.event_date.day == 5
    assert entries[0].event_date == date(2026, 7, 5)
    assert entries[-1].event_date == date(2026, 12, 5)


def test_mes_actual_se_salta_si_el_dia_ya_paso(db_session, seed_uy):
    income = _seed_income(db_session, payment_day=5)
    # hoy 2026-07-10: el 5 de julio ya pasó -> julio no se materializa
    materialize_income(db_session, income.id, today=date(2026, 7, 10), horizon=date(2026, 12, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 5  # ago..dic
    assert entries[0].event_date == date(2026, 8, 5)


def test_duracion_fija_genera_total_months(db_session, seed_uy):
    income = _seed_income(
        db_session,
        is_monthly_recurring=False,
        payment_day=None,
        first_income_date=date(2026, 8, 10),
        total_months=3,
    )
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 3  # ago, sep, oct
    assert [e.event_date for e in entries] == [date(2026, 8, 10), date(2026, 9, 10), date(2026, 10, 10)]


def test_cobro_unico(db_session, seed_uy):
    income = _seed_income(
        db_session,
        is_monthly_recurring=False,
        payment_day=None,
        first_income_date=date(2026, 8, 10),
        total_months=1,
    )
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 10)


def test_soft_deleted_borra_futuras_sin_pago(db_session, seed_uy):
    income = _seed_income(db_session)
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))
    assert len(_entries(db_session, income)) == 6

    income.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    assert len(_entries(db_session, income)) == 0


def test_idempotencia(db_session, seed_uy):
    income = _seed_income(db_session)
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    assert len(_entries(db_session, income)) == 6  # no duplica


def test_cambio_amount_actualiza_sin_duplicar(db_session, seed_uy):
    income = _seed_income(db_session)
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    income.amount = Decimal("50000.00")
    db_session.flush()
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 6
    assert all(e.amount == Decimal("50000.00") for e in entries)


def test_cambio_payment_day_mueve_in_place(db_session, seed_uy):
    income = _seed_income(db_session, payment_day=5)
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 9, 30))
    before = _entries(db_session, income)
    assert [e.event_date.day for e in before] == [5, 5, 5]  # jul, ago, sep
    ids_before = {e.id for e in before}

    income.payment_day = 20
    db_session.flush()
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 9, 30))

    after = _entries(db_session, income)
    assert len(after) == 3
    assert [e.event_date.day for e in after] == [20, 20, 20]
    assert {e.id for e in after} == ids_before  # misma fila, movida in place


def test_achicar_total_months_conserva_la_que_tiene_pago_real(db_session, seed_uy):
    income = _seed_income(
        db_session,
        is_monthly_recurring=False,
        payment_day=None,
        first_income_date=date(2026, 8, 10),
        total_months=4,  # ago, sep, oct, nov
    )
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))
    entries = _entries(db_session, income)
    assert len(entries) == 4
    nov = entries[-1]
    assert nov.event_date == date(2026, 11, 10)
    # un pago real imputado a la entry de noviembre
    db_session.add(CashFlowPayment(cash_flow_entry_id=nov.id, amount=Decimal("45000.00")))
    db_session.flush()

    income.total_months = 2  # ago, sep
    db_session.flush()
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    after = _entries(db_session, income)
    dates = [e.event_date for e in after]
    # ago y sep (objetivo) + nov (sobrevive por tener pago real); oct se borró
    assert date(2026, 8, 10) in dates
    assert date(2026, 9, 10) in dates
    assert date(2026, 11, 10) in dates
    assert date(2026, 10, 10) not in dates
    assert len(after) == 3


def test_shift_weekends_produce_dia_habil(db_session, seed_uy):
    # 2026-08-15 es sábado; con shift_weekends corre al lunes 2026-08-17
    income = _seed_income(db_session, payment_day=15, shift_weekends=True)
    materialize_income(db_session, income.id, today=date(2026, 8, 1), horizon=date(2026, 8, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 17)
