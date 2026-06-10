import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.credit_card import CreditCard
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.services import cash_flow_entry_service as svc


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    return db_session.execute(select(User)).scalars().all()[-1]


def _plan(db_session, user, *, is_default=False):
    plan = Plan(
        user_id=user.id, name="Plan", is_default=is_default, is_engine_generated=False,
        selected_at=datetime.now(timezone.utc), dial_amount=Decimal("0"), dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _card(db_session, user, *, deleted_at=None):
    card = CreditCard(
        user_id=user.id, institution_id=1, card_network_id=1, current_limit=Decimal("100000.00"),
        closing_day=13, due_day=25, financing_rate_local=Decimal("10.00"), overdue_rate_local=Decimal("12.00"),
        financing_rate_usd=Decimal("5.00"), overdue_rate_usd=Decimal("6.00"), rates_add_vat=False,
        review_findings="[]", is_ready=True, deleted_at=deleted_at,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def _entry(db_session, user, *, source_type, source_id, event_date, is_income=False, amount="6000.00", currency_id=1):
    e = CashFlowEntry(
        user_id=user.id, event_date=event_date, is_income=is_income, amount=Decimal(amount),
        currency_id=currency_id, source_type=source_type, source_id=source_id,
    )
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    return e


def _card_entry(db_session, user, **kw):
    card = _card(db_session, user)
    return _entry(db_session, user, source_type="tarjeta_credito", source_id=card.id, **kw)


def _income_entry(db_session, user, plan, *, event_date, amount="45000.00"):
    pm = PlanMovement(
        plan_id=plan.id, kind="ingreso", currency_id=1, principal_amount=Decimal(amount),
        start_date=date(2026, 1, 1), rates_add_vat=False,
    )
    db_session.add(pm)
    db_session.commit()
    db_session.refresh(pm)
    return _entry(
        db_session, user, source_type="plan_movimiento_entrada", source_id=pm.id,
        event_date=event_date, is_income=True, amount=amount,
    )


def _pay(db_session, entry, *, amount, plan_id=None, planned_date=None):
    p = CashFlowPayment(
        cash_flow_entry_id=entry.id, amount=Decimal(amount), plan_id=plan_id, planned_date=planned_date
    )
    db_session.add(p)
    db_session.commit()
    return p


def test_timeline_groups_by_month_and_flow(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00")     # egreso junio
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 5), amount="45000.00")  # ingreso junio
    r = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert [m["month"] for m in body["months"]] == ["2026-06"]
    jun = body["months"][0]
    assert len(jun["incomes"]) == 1 and len(jun["expenses"]) == 1
    assert "is_income" not in jun["incomes"][0]  # no se serializa
    assert body["open_debts"] == []
    # agregados con today fijo (deterministas)
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 5))
    jun_obj = out.months[0]
    assert jun_obj.pending_income == Decimal("45000.00")
    assert jun_obj.pending_expenses == Decimal("6000.00")
    assert jun_obj.balance == Decimal("39000.00")


def test_requires_plan_id(client, db_session, seed_cc_refs):
    headers = _headers(client)
    assert client.get("/cash-flow-entries", headers=headers).json()["code"] == "plan_id_required"


def test_plan_not_owned(client, db_session, seed_cc_refs):
    headers_a = _headers(client, email="a@b.com")
    user_a = _last_user(db_session)
    plan_a = _plan(db_session, user_a)
    headers_b = _headers(client, email="b@b.com")
    assert client.get(f"/cash-flow-entries?plan_id={plan_a.id}", headers=headers_b).status_code == 404


def test_plan_not_found(client, db_session, seed_cc_refs):
    headers = _headers(client)
    assert client.get(f"/cash-flow-entries?plan_id={uuid.uuid4()}", headers=headers).status_code == 404


def test_empty_timeline(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    assert client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json() == {"months": [], "open_debts": []}


def test_paid_real_and_planned_amount(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    entry = _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00")
    _pay(db_session, entry, amount="2000.00")  # real
    _pay(db_session, entry, amount="1000.00", plan_id=plan.id, planned_date=date(2026, 6, 10))  # planificado de este plan
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert e["paid_real"] == "2000.00"
    assert e["planned_amount"] == "1000.00"


def test_planned_of_other_plan_excluded(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    other = _plan(db_session, user)
    entry = _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00")
    _pay(db_session, entry, amount="999.00", plan_id=other.id, planned_date=date(2026, 6, 10))
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert e["planned_amount"] == "6000.00"  # sin planificado de este plan → cae a amount (el 999 de otro plan sigue excluido)


def test_plan_entry_only_for_its_plan(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    other = _plan(db_session, user)
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 5))  # entry del plan
    # pedido con OTRO plan: la entry de plan no aparece
    body = client.get(f"/cash-flow-entries?plan_id={other.id}", headers=headers).json()
    assert body == {"months": [], "open_debts": []}
    # pedido con SU plan: aparece
    body2 = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()
    assert len(body2["months"][0]["incomes"]) == 1


def _open_debt(db_session, user):
    from app.models.obligation import Obligation
    from app.models.obligation_type import ObligationType
    from app.models.priority_level import PriorityLevel

    db_session.merge(PriorityLevel(level=6, name="Ajustable", description="x"))
    db_session.flush()
    db_session.merge(
        ObligationType(
            id=8, obligation_kind="deuda_abierta", code="informal", name="Informal",
            description="x", default_priority_level=6, visible=True,
        )
    )
    db_session.flush()
    o = Obligation(
        user_id=user.id,
        obligation_type_id=8,
        priority_level=6,
        currency_id=1,
        amount=Decimal("30000.00"),
        is_monthly_recurring=False,
        due_day=None,
        first_due_date=None,
        total_installments=None,
        financing_rate=None,
        overdue_rate=None,
        rates_add_vat=False,
        shift_weekends=False,
        is_closed=False,
        review_findings="[]",
        is_ready=True,
    )
    db_session.add(o)
    db_session.commit()
    db_session.refresh(o)
    return o


def test_open_debt_madre_in_open_debts(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    debt = _open_debt(db_session, user)
    _entry(db_session, user, source_type="deuda_abierta", source_id=debt.id, event_date=None, amount="30000.00")
    body = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()
    assert body["months"] == []
    assert len(body["open_debts"]) == 1
    od = body["open_debts"][0]
    assert od["amount"] == "30000.00"
    assert od["planned_amount"] == "0.00"  # las open_debts NO reciben el fallback
    assert "event_date" not in od  # las de open_debts no traen event_date


def test_open_debt_projected_into_month(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    debt = _open_debt(db_session, user)
    entry = _entry(db_session, user, source_type="deuda_abierta", source_id=debt.id, event_date=None, amount="30000.00")
    _pay(db_session, entry, amount="5000.00", plan_id=plan.id, planned_date=date(2026, 7, 15))  # planificado julio
    body = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()
    # madre sigue en open_debts; además una proyección en julio (expenses), mismo id, amount = planificado del mes
    assert len(body["open_debts"]) == 1
    jul = next(m for m in body["months"] if m["month"] == "2026-07")
    proj = jul["expenses"][0]
    assert proj["id"] == str(entry.id)
    assert proj["amount"] == "5000.00"
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jul_obj = next(m for m in out.months if m.month == "2026-07")
    assert jul_obj.pending_expenses == Decimal("5000.00")


def test_description_credit_card_and_soft_deleted_included(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user, deleted_at=datetime.now(timezone.utc))  # soft-deleted
    _entry(db_session, user, source_type="tarjeta_credito", source_id=card.id, event_date=date(2026, 6, 10), amount="100.00")
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert e["description"] == "Scotiabank Amex"  # emisor + red (rama 4 no filtra deleted_at)


def test_conversion_x1_without_rate(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00", currency_id=1)
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert e["amount"] == "6000.00"
    assert e["amount_converted"] == "6000.00"  # Peso no cotiza -> COALESCE(...,1)


def test_conversion_scaled_with_rate(client, db_session, seed_cc_refs):
    # moneda no legal (Dólar) con una cotización en la fecha de la entry
    from app.models.currency import Currency
    from app.models.currency_rate import CurrencyRate
    db_session.add(Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True))
    db_session.commit()
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    db_session.add(CurrencyRate(currency_id=3, rate_date=date(2026, 6, 10), value=Decimal("40.000000")))
    db_session.commit()
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="10.00", currency_id=3)
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert Decimal(e["amount_converted"]) == Decimal("400.000000")  # 10 × 40


def test_months_ordered(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user)
    _entry(db_session, user, source_type="tarjeta_credito", source_id=card.id, event_date=date(2026, 8, 1), amount="1.00")
    _entry(db_session, user, source_type="tarjeta_credito", source_id=card.id, event_date=date(2026, 6, 1), amount="2.00")
    _entry(db_session, user, source_type="tarjeta_credito", source_id=card.id, event_date=date(2026, 7, 1), amount="3.00")
    months = [m["month"] for m in client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"]]
    assert months == ["2026-06", "2026-07", "2026-08"]


def test_planned_falls_back_to_amount_when_no_plan(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00")  # sin pago planificado
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert e["planned_amount"] == "6000.00"            # cae a amount
    assert e["planned_amount_converted"] == "6000.00"


def test_pending_nets_paid_real(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)  # dial 0
    e = _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00")
    _pay(db_session, e, amount="2000.00")  # pago real
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = out.months[0]
    assert jun.pending_expenses == Decimal("4000.00")  # efectivo 6000 − paid_real 2000


def _cash(db_session, user, currency_id, amount):
    from app.models.cash_balance import CashBalance
    db_session.add(CashBalance(user_id=user.id, currency_id=currency_id, amount=Decimal(amount)))
    db_session.commit()


def _plan_dial(db_session, user, dial_amount):
    plan = Plan(
        user_id=user.id, name="Plan", is_default=False, is_engine_generated=False,
        selected_at=datetime.now(timezone.utc), dial_amount=Decimal(dial_amount), dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def test_available_dial_and_balance_first_month(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan_dial(db_session, user, "42000.00")
    _cash(db_session, user, 1, "38500.00")  # Peso (cotiza x1)
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 10), amount="90000.00")
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="91225.70")
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = out.months[0]
    assert jun.available == Decimal("38500.00")
    assert jun.remaining_spending == Decimal("29400.00")  # (30-9)/30 * 42000
    # balance = (38500 + 90000) − (91225.70 + 29400) = 7874.30
    assert jun.balance == Decimal("7874.30")


def test_available_carries_balance_to_next_month(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan_dial(db_session, user, "0")  # dial 0 aísla el arrastre
    _cash(db_session, user, 1, "10000.00")
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 10), amount="5000.00")   # junio
    _card_entry(db_session, user, event_date=date(2026, 7, 10), amount="3000.00")            # julio
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun, jul = out.months[0], out.months[1]
    assert jun.balance == Decimal("15000.00")      # (10000 + 5000) − (0 + 0)
    assert jul.available == Decimal("15000.00")    # arrastre
    assert jul.balance == Decimal("12000.00")      # (15000 + 0) − (3000 + 0)


def _set_need(db_session, user, amount):
    from app.models.user_financial_settings import UserFinancialSettings
    db_session.add(UserFinancialSettings(user_id=user.id, monthly_need_amount=Decimal(amount)))
    db_session.commit()


def test_remaining_spending_uses_monthly_need_when_set(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan_dial(db_session, user, "42000.00")
    _set_need(db_session, user, "5000.00")
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="1000.00")
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    assert out.months[0].remaining_spending == Decimal("5000.00")  # el monto del usuario, no el prorrateo


def test_remaining_spending_falls_back_to_prorated_dial(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan_dial(db_session, user, "42000.00")  # sin user_financial_settings
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="1000.00")
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    assert out.months[0].remaining_spending == Decimal("29400.00")  # (30-9)/30 * 42000


def test_past_month_zeroed_and_not_carried(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan_dial(db_session, user, "0")
    _cash(db_session, user, 1, "10000.00")
    _card_entry(db_session, user, event_date=date(2026, 5, 10), amount="3000.00")            # mes pasado
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 10), amount="5000.00")    # mes actual
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    may, jun = out.months[0], out.months[1]
    assert may.month == "2026-05"
    assert may.available == Decimal("0")
    assert may.pending_income == Decimal("0")
    assert may.pending_expenses == Decimal("0")
    assert may.remaining_spending == Decimal("0")
    assert may.balance == Decimal("0")
    assert len(may.expenses) == 1                 # la row del mes pasado igual aparece
    assert jun.available == Decimal("10000.00")   # el mes actual arranca con el efectivo, sin arrastrar mayo
    assert jun.balance == Decimal("15000.00")     # (10000 + 5000) − (0 + 0)
