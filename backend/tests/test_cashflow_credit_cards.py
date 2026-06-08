# tests/test_cashflow_credit_cards.py
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.credit_card import CreditCard
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem
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


@pytest.fixture
def sub_type(db_session, user_uy):
    """Agrega el tipo de ítem 'suscripcion' (id 3). Devuelve su id. Reusa user_uy."""
    db_session.add(
        CreditCardItemType(id=3, code="suscripcion", name="Suscripción", description="x")
    )
    db_session.flush()
    return 3


def _add_item(db_session, statement, *, amount, currency_id, item_type_id,
              current_installment=None, total_installments=None,
              charge_date=date(2026, 2, 2), description="X"):
    item = CreditCardStatementItem(
        credit_card_statement_id=statement.id,
        charge_date=charge_date,
        description=description,
        amount=amount,
        currency_id=currency_id,
        current_installment=current_installment,
        total_installments=total_installments,
        item_type_id=item_type_id,
    )
    db_session.add(item)
    db_session.flush()
    return item


def _by_key(db_session, card):
    return {(e.issue_year, e.issue_month, e.currency_id): e for e in _orm_entries(db_session, card)}


def test_pending_installment_projects_remaining_months(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))  # solo local en R1
    _add_item(db_session, st, amount=Decimal("1997.50"), currency_id=1, item_type_id=1,
              current_installment=3, total_installments=4)  # 3/4 -> falta 1 (junio)
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    keys = _by_key(db_session, card)
    assert (2026, 6, 1) in keys
    junio = keys[(2026, 6, 1)]
    assert junio.amount == Decimal("1997.50")
    assert junio.event_date == date(2026, 6, 13)
    assert junio.minimum_payment is None
    assert (2026, 7, 1) not in keys  # no hay más cuotas


def test_subscription_projects_every_month(db_session, user_uy, sub_type):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("69.99"), currency_id=3, item_type_id=sub_type)
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    usd_months = sorted(m for (y, m, c) in _by_key(db_session, card) if c == 3)
    assert usd_months == [6, 7, 8, 9, 10, 11, 12]  # junio..diciembre
    sample = _by_key(db_session, card)[(2026, 7, 3)]
    assert sample.amount == Decimal("69.99")
    assert sample.event_date == date(2026, 7, 13)
    assert sample.minimum_payment is None


def test_one_payment_not_projected(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("500.00"), currency_id=1, item_type_id=1)  # sin cuotas, compra
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    future = [(y, m) for (y, m, c) in _by_key(db_session, card) if (y, m) != (2026, 5)]
    assert future == []  # solo el resumen de mayo (R1), nada proyectado


def test_grouping_sums_same_month_currency(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("100.00"), currency_id=1, item_type_id=1,
              current_installment=1, total_installments=2)  # -> junio
    _add_item(db_session, st, amount=Decimal("50.00"), currency_id=1, item_type_id=1,
              current_installment=1, total_installments=2)  # -> junio
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    assert _by_key(db_session, card)[(2026, 6, 1)].amount == Decimal("150.00")


def test_closing_day_clamped_in_projection(db_session, user_uy, sub_type):
    card = _make_card(db_session, user_uy, closing_day=31)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("69.99"), currency_id=3, item_type_id=sub_type)
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 6, 30))
    assert _by_key(db_session, card)[(2026, 6, 3)].event_date == date(2026, 6, 30)  # junio no tiene 31


def test_projection_becomes_real(db_session, user_uy, sub_type):
    card = _make_card(db_session, user_uy, closing_day=13)
    st_apr = _make_statement(db_session, card, issue_year=2026, issue_month=4, closing_day=13, due_day=25,
                             total_local=Decimal("1000.00"), total_usd=Decimal("0.00"),
                             min_local=Decimal("100.00"))
    _add_item(db_session, st_apr, amount=Decimal("100.00"), currency_id=1, item_type_id=sub_type)
    materialize_credit_card(db_session, card.id, today=date(2026, 4, 1), horizon=date(2026, 12, 31))
    # mayo quedó proyectado (suscripción), minimum_payment NULL
    proj_may = _by_key(db_session, card)[(2026, 5, 1)]
    assert proj_may.minimum_payment is None
    assert proj_may.amount == Decimal("100.00")
    # llega el resumen real de mayo
    st_may = _make_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=13, due_day=25,
                             total_local=Decimal("5000.00"), total_usd=Decimal("0.00"),
                             min_local=Decimal("300.00"))
    _add_item(db_session, st_may, amount=Decimal("100.00"), currency_id=1, item_type_id=sub_type)
    materialize_credit_card(db_session, card.id, today=date(2026, 5, 1), horizon=date(2026, 12, 31))
    keys = _by_key(db_session, card)
    real_may = keys[(2026, 5, 1)]
    assert real_may.amount == Decimal("5000.00")     # pisada por R1
    assert real_may.minimum_payment == Decimal("300.00")
    assert real_may.event_date == date(2026, 5, 25)
    # no se duplicó: una sola entry para (2026, 5, 1)
    assert sum(1 for (y, m, c) in keys if (y, m, c) == (2026, 5, 1)) == 1


def test_reprojection_deletes_stale_future(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    item = _add_item(db_session, st, amount=Decimal("100.00"), currency_id=1, item_type_id=1,
                     current_installment=1, total_installments=3)  # falta 2 -> junio, julio
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    keys = _by_key(db_session, card)
    assert (2026, 6, 1) in keys and (2026, 7, 1) in keys
    item.current_installment = 3  # ya no faltan cuotas
    db_session.flush()
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    keys = _by_key(db_session, card)
    assert (2026, 6, 1) not in keys and (2026, 7, 1) not in keys  # proyecciones futuras borradas
