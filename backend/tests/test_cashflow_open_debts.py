import pytest
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.user import User
from app.services.cash_flow.open_debts import materialize_open_debt


@pytest.fixture
def user(db_session, seed_uy_currency):
    db_session.flush()
    db_session.add(
        ObligationType(id=8, obligation_kind="deuda_abierta", code="informal", name="Informal",
                       description="x", visible=True)
    )
    db_session.flush()
    u = User(country_code="UY")
    db_session.add(u)
    db_session.flush()
    return u


def _open_debt(db_session, user, **overrides):
    kwargs = dict(
        user_id=user.id,
        obligation_type_id=8,
                currency_id=1,
        amount=Decimal("8000.00"),
        is_monthly_recurring=False,
        due_day=None,
        first_due_date=None,
        total_installments=None,
        financing_rate=None,
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
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "deuda_abierta",
                CashFlowEntry.source_id == obligation_id,
            )
        ).scalars()
    )


def test_materializa_una_fila(db_session, user):
    o = _open_debt(db_session, user)
    materialize_open_debt(db_session, o.id)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    e = entries[0]
    assert e.event_date is None
    assert e.is_income is False
    assert e.source_type == "deuda_abierta"
    assert e.amount == Decimal("8000.00")
    assert e.currency_id == 1
    assert e.financing_rate is None and e.overdue_rate is None


def test_idempotente_no_duplica(db_session, user):
    o = _open_debt(db_session, user)
    materialize_open_debt(db_session, o.id)
    materialize_open_debt(db_session, o.id)
    assert len(_entries(db_session, o.id)) == 1


def test_edita_amount_actualiza_misma_fila(db_session, user):
    o = _open_debt(db_session, user)
    materialize_open_debt(db_session, o.id)
    entry_id = _entries(db_session, o.id)[0].id
    o.amount = Decimal("3000.00")
    db_session.flush()
    materialize_open_debt(db_session, o.id)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].id == entry_id
    assert entries[0].amount == Decimal("3000.00")


def test_gate_not_ready_no_materializa(db_session, user):
    o = _open_debt(db_session, user, is_ready=False)
    materialize_open_debt(db_session, o.id)
    assert _entries(db_session, o.id) == []


def test_is_closed_no_borra(db_session, user):
    o = _open_debt(db_session, user)
    materialize_open_debt(db_session, o.id)
    entry_id = _entries(db_session, o.id)[0].id
    o.is_closed = True
    o.amount = Decimal("5000.00")  # la acción de cierre ajusta el total pagado
    db_session.flush()
    materialize_open_debt(db_session, o.id)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].id == entry_id
    assert entries[0].amount == Decimal("5000.00")


def test_no_toca_pagos(db_session, user):
    o = _open_debt(db_session, user)
    materialize_open_debt(db_session, o.id)
    e = _entries(db_session, o.id)[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=e.id, amount=Decimal("2000.00")))  # real
    db_session.flush()
    o.amount = Decimal("6000.00")
    db_session.flush()
    materialize_open_debt(db_session, o.id)
    pagos = list(
        db_session.execute(
            select(CashFlowPayment).where(CashFlowPayment.cash_flow_entry_id == e.id)
        ).scalars()
    )
    assert len(pagos) == 1
    assert _entries(db_session, o.id)[0].amount == Decimal("6000.00")
