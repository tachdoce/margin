import calendar
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_balance import CashBalance
from app.models.cash_flow_entry import CashFlowEntry
from app.models.currency_rate import CurrencyRate
from app.models.plan import Plan
from app.models.user import User
from app.models.user_financial_settings import UserFinancialSettings
from app.schemas.cash_flow_entry import MonthEntryOut, MonthOut, TimelineEntryOut, TimelineOut
from app.services.cash_flow.constants import PROJECTED_MINIMUM_RATE
from app.services.cash_flow.interest import monthly_carry, monthly_interest

_TIMELINE_SQL = text(
    """
WITH entries AS (
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, o.description,
         COALESCE(cfe.financing_rate, 0) AS financing_rate,
         COALESCE(cfe.overdue_rate, 0)   AS overdue_rate,
         cfe.amount                      AS minimum_payment
  FROM cash_flow_entries cfe
  JOIN obligations o ON o.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type IN ('gasto', 'deuda', 'deuda_abierta')
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, i.description,
         0 AS financing_rate, 0 AS overdue_rate, 0 AS minimum_payment
  FROM cash_flow_entries cfe
  JOIN incomes i ON i.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type = 'ingreso'
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, pm.description,
         COALESCE(cfe.financing_rate, 0) AS financing_rate,
         COALESCE(cfe.overdue_rate, 0)   AS overdue_rate,
         cfe.amount                      AS minimum_payment
  FROM cash_flow_entries cfe
  JOIN plan_movements pm ON pm.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type IN ('plan_movimiento', 'plan_movimiento_entrada')
    AND pm.plan_id = :plan_id
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income,
         inst.name || ' ' || ccn.name AS description,
         COALESCE(cfe.financing_rate, 0) AS financing_rate,
         COALESCE(cfe.overdue_rate, 0)   AS overdue_rate,
         cfe.minimum_payment             AS minimum_payment
  FROM cash_flow_entries cfe
  JOIN credit_cards cc          ON cc.id = cfe.source_id
  JOIN institutions inst        ON inst.id = cc.institution_id
  JOIN credit_card_networks ccn ON ccn.id = cc.card_network_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type = 'tarjeta_credito'
),
entries_with_payments AS (
  SELECT
    e.id, e.event_date, e.amount, e.currency_id,
    e.source_type, e.source_id, e.is_income, e.description,
    e.financing_rate, e.overdue_rate, e.minimum_payment,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id IS NULL), 0.00)    AS paid_real,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0.00) AS planned_amount
  FROM entries e
  LEFT JOIN cash_flow_payments p ON p.cash_flow_entry_id = e.id
  GROUP BY e.id, e.event_date, e.amount, e.currency_id,
           e.source_type, e.source_id, e.is_income, e.description,
           e.financing_rate, e.overdue_rate, e.minimum_payment
),
open_debt_monthly AS (
  SELECT
    cfe.id,
    MIN(COALESCE(p.planned_date, p.created_at::date))              AS event_date,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0.00) AS amount,
    cfe.currency_id,
    cfe.source_type,
    cfe.source_id,
    cfe.is_income,
    o.description,
    0 AS financing_rate, 0 AS overdue_rate, 0 AS minimum_payment,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id IS NULL), 0.00)    AS paid_real,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0.00) AS planned_amount
  FROM cash_flow_payments p
  JOIN cash_flow_entries cfe ON cfe.id = p.cash_flow_entry_id
  JOIN obligations o ON o.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type = 'deuda_abierta'
    AND (p.plan_id IS NULL OR p.plan_id = :plan_id)
  GROUP BY cfe.id, cfe.currency_id, cfe.source_type, cfe.source_id,
           cfe.is_income, o.description,
           date_trunc('month', COALESCE(p.planned_date, p.created_at::date))
),
unified AS (
  SELECT * FROM entries_with_payments
  UNION ALL
  SELECT * FROM open_debt_monthly
)
SELECT
  u.id, u.event_date, u.amount, u.currency_id,
  u.source_type, u.source_id, u.is_income, u.description,
  u.paid_real, u.planned_amount,
  u.amount         * COALESCE(cr.value, 1) AS amount_converted,
  u.paid_real      * COALESCE(cr.value, 1) AS paid_real_converted,
  u.planned_amount * COALESCE(cr.value, 1) AS planned_amount_converted,
  u.financing_rate, u.overdue_rate, u.minimum_payment
FROM unified u
LEFT JOIN currency_rates cr
  ON cr.currency_id = u.currency_id
  AND cr.rate_date  = COALESCE(u.event_date, CURRENT_DATE)
ORDER BY u.event_date ASC NULLS LAST
"""
)


def _entry_fields(r) -> dict:
    return dict(
        id=r["id"],
        amount=r["amount"],
        paid_real=r["paid_real"],
        planned_amount=r["planned_amount"],
        currency_id=r["currency_id"],
        source_type=r["source_type"],
        source_id=r["source_id"],
        description=r["description"],
        amount_converted=r["amount_converted"],
        paid_real_converted=r["paid_real_converted"],
        planned_amount_converted=r["planned_amount_converted"],
        financing_rate=r["financing_rate"],
        overdue_rate=r["overdue_rate"],
        minimum_payment=r["minimum_payment"],
    )


def _effective_planned(planned_amount, planned_amount_converted, amount, amount_converted):
    """Monto efectivo: el planificado si lo hay, si no el proyectado (amount)."""
    if planned_amount > 0:
        return planned_amount, planned_amount_converted
    return amount, amount_converted


def _rate(db: Session, currency_id: int, on_date: date) -> Decimal:
    r = db.get(CurrencyRate, (currency_id, on_date))
    return r.value if r is not None else Decimal("1")


def _available_now(db: Session, user: User, today: date) -> Decimal:
    total = Decimal("0")
    for cb in db.execute(select(CashBalance).where(CashBalance.user_id == user.id)).scalars():
        total += cb.amount * _rate(db, cb.currency_id, today)
    return total


def _healthy_debt_month(months: list[MonthOut], current_key: str) -> str | None:
    """Mes tras el último con generated_interest > 0 (entre los meses activos). None si el
    interés llega hasta el final del horizonte; primer mes activo si nunca hubo interés."""
    active = [m for m in months if m.month >= current_key]
    if not active:
        return None
    last = None
    for i, m in enumerate(active):
        if m.generated_interest > 0:
            last = i
    if last is None:
        return active[0].month
    if last + 1 >= len(active):
        return None
    return active[last + 1].month


def _goal_reached_month(
    months: list[MonthOut], current_key: str, healthy_month: str | None, goal_local: Decimal | None
) -> str | None:
    """Primer mes activo >= healthy_month con balance >= goal_local. None si no hay objetivo,
    no hay deuda sana, o no se alcanza."""
    if healthy_month is None or goal_local is None:
        return None
    for m in months:
        if m.month < current_key:
            continue
        if m.month >= healthy_month and m.balance >= goal_local:
            return m.month
    return None


def get_timeline(db: Session, user: User, plan_id: uuid.UUID | None, today: date | None = None) -> TimelineOut:
    if plan_id is None:
        raise AppError(ErrorCode.plan_id_required)
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise AppError(ErrorCode.not_found)

    today = today or date.today()
    dial = plan.dial_amount * _rate(db, plan.dial_currency_id, today)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    remaining_days = days_in_month - (today.day - 1)
    dial_prorated = (dial * Decimal(remaining_days) / Decimal(days_in_month)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    _settings = db.get(UserFinancialSettings, user.id)
    monthly_need = _settings.monthly_need_amount if _settings is not None else None

    rows = db.execute(_TIMELINE_SQL, {"user_id": user.id, "plan_id": plan_id}).mappings().all()

    current_key = today.strftime("%Y-%m")

    # cascada del arrastre de tarjeta: por (tarjeta, moneda), en orden de event_date
    carry_in: dict = {}       # row id -> arrastre que se suma a esa row
    min_override: dict = {}   # row id -> minimum recomputado (15%) cuando hubo arrastre
    generated_interest: dict = {}   # "YYYY-MM" -> interés generado ese mes (convertido)
    series: dict = {}
    for r in rows:
        if r["event_date"] is not None and r["source_type"] == "tarjeta_credito":
            series.setdefault((r["source_id"], r["currency_id"]), []).append(r)
    for serie in series.values():
        serie.sort(key=lambda r: r["event_date"])
        cin = Decimal("0")
        for r in serie:
            carry_in[r["id"]] = cin
            amount = r["amount"] + cin
            # el planificado es la intención total del mes; el real es su ejecución parcial
            if r["planned_amount"] > 0:
                payment = r["planned_amount"]
            elif r["paid_real"] > 0:
                payment = r["paid_real"]
            else:
                payment = amount  # sin plan ni pago: se asume pago total -> no arrastra
            if cin > 0:
                minimum = (amount * PROJECTED_MINIMUM_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                min_override[r["id"]] = minimum
            else:
                minimum = r["minimum_payment"]
            interest = monthly_interest(amount, payment, minimum, r["financing_rate"], r["overdue_rate"])
            if interest > 0:
                mk = r["event_date"].strftime("%Y-%m")
                generated_interest[mk] = generated_interest.get(mk, Decimal("0")) + interest * _rate(
                    db, r["currency_id"], r["event_date"]
                )
            cin = monthly_carry(amount, payment, minimum, r["financing_rate"], r["overdue_rate"])

    open_debts: list[TimelineEntryOut] = []
    buckets: dict[str, dict] = {}  # "YYYY-MM" -> {"incomes", "expenses", "pi", "pe"}

    for r in rows:
        if r["event_date"] is None:
            open_debts.append(TimelineEntryOut(**_entry_fields(r)))
            continue
        key = r["event_date"].strftime("%Y-%m")
        b = buckets.setdefault(key, {"incomes": [], "expenses": [], "pi": Decimal("0"), "pe": Decimal("0")})
        amount = r["amount"]
        amount_converted = r["amount_converted"]
        minimum_payment = r["minimum_payment"]
        cin = carry_in.get(r["id"], Decimal("0"))
        if cin > 0:
            amount = amount + cin
            amount_converted = amount_converted + cin * _rate(db, r["currency_id"], r["event_date"])
            minimum_payment = min_override[r["id"]]
        eff_pa, eff_pac = _effective_planned(r["planned_amount"], r["planned_amount_converted"], amount, amount_converted)
        fields = _entry_fields(r)
        fields["amount"] = amount
        fields["amount_converted"] = amount_converted
        fields["minimum_payment"] = minimum_payment
        fields["planned_amount"] = eff_pa
        fields["planned_amount_converted"] = eff_pac
        entry = MonthEntryOut(event_date=r["event_date"], **fields)
        pending = eff_pac - r["paid_real_converted"]
        if r["is_income"]:
            b["incomes"].append(entry)
            b["pi"] += pending
        else:
            b["expenses"].append(entry)
            b["pe"] += pending

    months: list[MonthOut] = []
    prev_balance: Decimal | None = None
    for key in sorted(buckets):
        b = buckets[key]
        b["incomes"].sort(key=lambda e: (e.event_date, str(e.id)))
        b["expenses"].sort(key=lambda e: (e.event_date, str(e.id)))
        if key < current_key:
            # mes pasado: histórico, totales en 0, no arrastra
            available = pending_income = pending_expenses = remaining_spending = balance = Decimal("0")
            gen = Decimal("0")
        else:
            gen = generated_interest.get(key, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if prev_balance is None:  # primer mes >= actual = ancla del efectivo
                available = _available_now(db, user, today)
                if key == current_key:
                    remaining_spending = monthly_need if monthly_need is not None else dial_prorated
                else:
                    remaining_spending = dial
            else:
                available = prev_balance
                remaining_spending = dial
            pending_income = b["pi"]
            pending_expenses = b["pe"]
            balance = (available + pending_income) - (pending_expenses + remaining_spending)
            prev_balance = balance
        months.append(
            MonthOut(
                month=key,
                available=available,
                pending_income=pending_income,
                pending_expenses=pending_expenses,
                remaining_spending=remaining_spending,
                balance=balance,
                generated_interest=gen,
                incomes=[e for e in b["incomes"] if e.amount != 0],
                expenses=[e for e in b["expenses"] if e.amount != 0],
            )
        )

    healthy_month = _healthy_debt_month(months, current_key)
    goal_local = None
    if plan.goal_amount is not None and plan.goal_currency_id is not None:
        goal_local = plan.goal_amount * _rate(db, plan.goal_currency_id, today)
    goal_month = _goal_reached_month(months, current_key, healthy_month, goal_local)
    return TimelineOut(
        months=months,
        open_debts=[e for e in open_debts if e.amount != 0],
        healthy_debt_month=healthy_month,
        goal_reached_month=goal_month,
    )


EDITABLE_ENTRY_SOURCE_TYPES = (
    "gasto",
    "deuda",
    "deuda_abierta",
    "ingreso",
    "plan_movimiento",
    "plan_movimiento_entrada",
)  # tarjeta_credito excluido: el monto sale del resumen real y el motor lo pisa


def list_by_source(db, user, source_id, *, today: date | None = None):
    if source_id is None:
        raise AppError(ErrorCode.source_id_required)
    today = today or date.today()

    # resolución polimórfica: el source_type sale de las propias entries (no de obligations)
    source_type = db.execute(
        select(CashFlowEntry.source_type)
        .where(CashFlowEntry.source_id == source_id, CashFlowEntry.user_id == user.id)
        .limit(1)
    ).scalar_one_or_none()
    if source_type is None:
        raise AppError(ErrorCode.not_found)
    if source_type not in EDITABLE_ENTRY_SOURCE_TYPES:
        raise AppError(ErrorCode.source_not_editable)

    month_start = today.replace(day=1)
    stmt = (
        select(CashFlowEntry)
        .where(
            CashFlowEntry.user_id == user.id,
            CashFlowEntry.source_id == source_id,
            CashFlowEntry.source_type.in_(EDITABLE_ENTRY_SOURCE_TYPES),
            CashFlowEntry.event_date >= month_start,
        )
        .order_by(CashFlowEntry.event_date.asc())
    )
    return list(db.execute(stmt).scalars())


def update_entry_amount(db, user, entry_id, amount, *, today: date | None = None):
    today = today or date.today()
    entry = db.get(CashFlowEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    if entry.source_type not in EDITABLE_ENTRY_SOURCE_TYPES:
        raise AppError(ErrorCode.source_not_editable)
    if entry.event_date is None or entry.event_date < today.replace(day=1):
        raise AppError(ErrorCode.entry_not_editable)
    if amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")
    entry.amount = amount
    db.flush()
    db.commit()
    db.refresh(entry)
    return entry
