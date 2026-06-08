# tests/test_cashflow_credit_cards.py
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.currency import Currency
from app.services.cash_flow.credit_cards import materialize_credit_card
from app.services.scoping import credit_card_usd_currency

from tests.test_credit_cards_model import _card_kwargs

TODAY = date(2026, 5, 1)


@pytest.fixture
def user_uy(db_session, seed_cc_refs):
    # seed_cc_refs ya siembra Peso (id 1). Agregamos el USD (Dólar id 3).
    db_session.add(
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True)
    )
    db_session.flush()
    return seed_cc_refs


def _make_card(db_session, user, **over):
    kwargs = _card_kwargs(user)  # rates _local/_usd seteadas, closing_day 13, is_ready False
    kwargs["is_ready"] = True
    kwargs.update(over)
    card = CreditCard(**kwargs)
    db_session.add(card)
    db_session.flush()
    return card


def _make_statement(db_session, card, *, issue_year=2026, issue_month=5, closing_day=13, due_day=25,
                    total_local=Decimal("7991.28"), total_usd=Decimal("65.35"),
                    min_local=Decimal("600.00"), min_usd=Decimal("0.00")):
    st = CreditCardStatement(
        credit_card_id=card.id,
        issue_year=issue_year,
        issue_month=issue_month,
        closing_date=date(issue_year, issue_month, closing_day),
        due_date=date(issue_year, issue_month, due_day),
        total_local=total_local,
        total_usd=total_usd,
        minimum_payment_local=min_local,
        minimum_payment_usd=min_usd,
    )
    db_session.add(st)
    db_session.flush()
    return st


def _orm_entries(db_session, card):
    from sqlalchemy import select

    return list(
        db_session.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "tarjeta_credito",
                CashFlowEntry.source_id == card.id,
            )
        ).scalars()
    )


def test_usd_currency_helper(db_session, user_uy):
    assert credit_card_usd_currency(db_session, user_uy).id == 3


def test_gate_not_ready_writes_nothing(db_session, user_uy):
    card = _make_card(db_session, user_uy, is_ready=False)
    _make_statement(db_session, card)
    materialize_credit_card(db_session, card.id, today=TODAY)
    assert _orm_entries(db_session, card) == []


def test_missing_card_is_noop(db_session, user_uy):
    materialize_credit_card(db_session, uuid.uuid4(), today=TODAY)  # no existe -> sin error


def test_two_currencies(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card)
    materialize_credit_card(db_session, card.id, today=TODAY)
    entries = {e.currency_id: e for e in _orm_entries(db_session, card)}
    assert set(entries) == {1, 3}
    local = entries[1]
    assert local.amount == Decimal("7991.28")
    assert local.event_date == date(2026, 5, 25)
    assert (local.issue_year, local.issue_month) == (2026, 5)
    assert local.minimum_payment == Decimal("600.00")
    assert local.is_income is False
    assert local.financing_rate == Decimal("85.38")  # 69.98 * 1.22
    assert local.overdue_rate == Decimal("99.15")    # 81.27 * 1.22
    usd = entries[3]
    assert usd.amount == Decimal("65.35")
    assert usd.minimum_payment == Decimal("0.00")
    assert usd.financing_rate == Decimal("16.47")  # 13.50 * 1.22
    assert usd.overdue_rate == Decimal("19.13")    # 15.68 * 1.22


def test_zero_usd_total_only_local(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card, total_usd=Decimal("0.00"))
    materialize_credit_card(db_session, card.id, today=TODAY)
    entries = _orm_entries(db_session, card)
    assert len(entries) == 1
    assert entries[0].currency_id == 1


def test_reconcile_updates_not_duplicates(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    st = _make_statement(db_session, card, total_local=Decimal("100.00"), total_usd=Decimal("0.00"))
    materialize_credit_card(db_session, card.id, today=TODAY)
    st.total_local = Decimal("200.00")
    db_session.flush()
    materialize_credit_card(db_session, card.id, today=TODAY)
    entries = _orm_entries(db_session, card)
    assert len(entries) == 1
    assert entries[0].amount == Decimal("200.00")


def test_currency_that_lost_total_is_deleted(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    st = _make_statement(db_session, card, total_usd=Decimal("65.35"))
    materialize_credit_card(db_session, card.id, today=TODAY)
    assert any(e.currency_id == 3 for e in _orm_entries(db_session, card))
    st.total_usd = Decimal("0.00")
    db_session.flush()
    materialize_credit_card(db_session, card.id, today=TODAY)
    cids = {e.currency_id for e in _orm_entries(db_session, card)}
    assert cids == {1}  # la fila USD futura se borró


def test_no_delete_when_real_payment(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    st = _make_statement(db_session, card, total_usd=Decimal("65.35"))
    materialize_credit_card(db_session, card.id, today=TODAY)
    usd = next(e for e in _orm_entries(db_session, card) if e.currency_id == 3)
    db_session.add(CashFlowPayment(cash_flow_entry_id=usd.id, amount=Decimal("10.00"), plan_id=None))
    db_session.flush()
    st.total_usd = Decimal("0.00")
    db_session.flush()
    with pytest.raises(RuntimeError):
        materialize_credit_card(db_session, card.id, today=TODAY)


def test_past_entry_not_touched(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card)  # último: 2026/5
    # entry pasada (2026/3) fuera del target, event_date < today
    past = CashFlowEntry(
        user_id=card.user_id,
        event_date=date(2026, 3, 25),
        is_income=False,
        amount=Decimal("500.00"),
        currency_id=1,
        issue_year=2026,
        issue_month=3,
        source_type="tarjeta_credito",
        source_id=card.id,
    )
    db_session.add(past)
    db_session.flush()
    materialize_credit_card(db_session, card.id, today=TODAY)
    keys = {(e.issue_year, e.issue_month, e.currency_id) for e in _orm_entries(db_session, card)}
    assert (2026, 3, 1) in keys  # la pasada sigue
