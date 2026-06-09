import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.plan import Plan
from app.models.user import User
from app.schemas.cash_flow_entry import MonthEntryOut, MonthOut, TimelineEntryOut, TimelineOut

_TIMELINE_SQL = text(
    """
WITH entries AS (
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, o.description
  FROM cash_flow_entries cfe
  JOIN obligations o ON o.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type IN ('gasto', 'deuda', 'deuda_abierta')
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, i.description
  FROM cash_flow_entries cfe
  JOIN incomes i ON i.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type = 'ingreso'
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, pm.description
  FROM cash_flow_entries cfe
  JOIN plan_movements pm ON pm.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type IN ('plan_movimiento', 'plan_movimiento_entrada')
    AND pm.plan_id = :plan_id
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income,
         inst.name || ' ' || ccn.name AS description
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
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id IS NULL), 0.00)    AS paid_real,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0.00) AS planned_amount
  FROM entries e
  LEFT JOIN cash_flow_payments p ON p.cash_flow_entry_id = e.id
  GROUP BY e.id, e.event_date, e.amount, e.currency_id,
           e.source_type, e.source_id, e.is_income, e.description
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
  u.planned_amount * COALESCE(cr.value, 1) AS planned_amount_converted
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
    )


def get_timeline(db: Session, user: User, plan_id: uuid.UUID | None) -> TimelineOut:
    if plan_id is None:
        raise AppError(ErrorCode.plan_id_required)
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise AppError(ErrorCode.not_found)

    rows = db.execute(_TIMELINE_SQL, {"user_id": user.id, "plan_id": plan_id}).mappings().all()

    open_debts: list[TimelineEntryOut] = []
    buckets: dict[str, dict] = {}  # "YYYY-MM" -> {"incomes": [], "expenses": [], "ti": Decimal, "te": Decimal}

    for r in rows:
        if r["event_date"] is None:
            open_debts.append(TimelineEntryOut(**_entry_fields(r)))
            continue
        key = r["event_date"].strftime("%Y-%m")
        b = buckets.setdefault(key, {"incomes": [], "expenses": [], "ti": Decimal("0"), "te": Decimal("0")})
        entry = MonthEntryOut(event_date=r["event_date"], **_entry_fields(r))
        if r["is_income"]:
            b["incomes"].append(entry)
            b["ti"] += r["amount_converted"]
        else:
            b["expenses"].append(entry)
            b["te"] += r["amount_converted"]

    months: list[MonthOut] = []
    for key in sorted(buckets):
        b = buckets[key]
        b["incomes"].sort(key=lambda e: (e.event_date, str(e.id)))
        b["expenses"].sort(key=lambda e: (e.event_date, str(e.id)))
        months.append(
            MonthOut(
                month=key,
                total_income=b["ti"],
                total_expenses=b["te"],
                balance=b["ti"] - b["te"],
                incomes=b["incomes"],
                expenses=b["expenses"],
            )
        )

    return TimelineOut(months=months, open_debts=open_debts)


EDITABLE_ENTRY_SOURCE_TYPES = ("gasto",)


def list_by_source(db, user, source_id, *, today: date | None = None):
    if source_id is None:
        raise AppError(ErrorCode.source_id_required)
    today = today or date.today()

    kind = db.execute(
        select(ObligationType.obligation_kind)
        .join(Obligation, Obligation.obligation_type_id == ObligationType.id)
        .where(Obligation.id == source_id, Obligation.user_id == user.id)
    ).scalar_one_or_none()
    if kind is None:
        raise AppError(ErrorCode.not_found)
    if kind not in EDITABLE_ENTRY_SOURCE_TYPES:
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
