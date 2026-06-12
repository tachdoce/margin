"""PlanningEngine: decide qué pagar de cada egreso dentro de un plan.

Simula mes a mes (espejo de la matemática de get_timeline), asigna por prioridad
(obligatorios -> mínimos -> avalancha por tasa con look-ahead) y materializa la decisión
como cash_flow_payments con is_auto_generated=true.
Spec: docs/superpowers/specs/2026-06-11-planning-engine-design.md
"""
import calendar
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.models.user_financial_settings import UserFinancialSettings
from app.services.cash_flow.constants import PROJECTED_MINIMUM_RATE
from app.services.cash_flow.interest import monthly_carry

# misma conversión y mismo ancla de efectivo que el timeline
from app.services.cash_flow_entry_service import _available_now, _rate

Q = Decimal("0.01")
ZERO = Decimal("0")
_PLAN_TYPES = ("plan_movimiento", "plan_movimiento_entrada")


@dataclass
class _Entry:
    id: uuid.UUID
    event_date: date
    is_income: bool
    source_type: str
    source_id: uuid.UUID
    currency_id: int
    base_amount: Decimal
    financing_rate: Decimal
    overdue_rate: Decimal
    minimum_payment: Decimal | None  # solo tarjetas (en el resto viene None)
    paid_real: Decimal
    manual: Decimal
    fx: Decimal
    carry_in: Decimal = ZERO   # arrastre del propio motor (tarjetas)
    decided: Decimal = ZERO    # decisión del motor (pago total del mes)

    @property
    def month(self) -> tuple[int, int]:
        return (self.event_date.year, self.event_date.month)

    @property
    def amount(self) -> Decimal:
        """Monto efectivo: base + arrastre."""
        return self.base_amount + self.carry_in

    @property
    def has_rates(self) -> bool:
        return self.financing_rate > 0 or self.overdue_rate > 0

    @property
    def is_card(self) -> bool:
        return self.source_type == "tarjeta_credito"

    @property
    def minimum(self) -> Decimal:
        """Tarjeta con arrastre: 15% del efectivo (regla del timeline); tarjeta sin
        arrastre: el de la entry; deudas/plan_movements con tasas: el total."""
        if self.is_card:
            if self.carry_in > 0:
                return (self.amount * PROJECTED_MINIMUM_RATE).quantize(Q, rounding=ROUND_HALF_UP)
            return self.minimum_payment if self.minimum_payment is not None else self.amount
        return self.amount

    @property
    def committed(self) -> Decimal:
        """Compromiso previo: manual si > 0, si no real (espejo de _effective_planned)."""
        if self.manual > 0:
            return self.manual
        return self.paid_real

    @property
    def saldo(self) -> Decimal:
        return self.amount - self.decided

    def consumption(self) -> Decimal:
        """Plata que falta salir del efectivo por esta entry, convertida."""
        return max(ZERO, self.decided - self.paid_real) * self.fx


def _payment_sums(db: Session, entry_ids: list[uuid.UUID], plan: Plan) -> tuple[dict, dict]:
    if not entry_ids:
        return {}, {}
    paid = dict(
        db.execute(
            select(CashFlowPayment.cash_flow_entry_id, func.sum(CashFlowPayment.amount))
            .where(CashFlowPayment.cash_flow_entry_id.in_(entry_ids), CashFlowPayment.plan_id.is_(None))
            .group_by(CashFlowPayment.cash_flow_entry_id)
        ).all()
    )
    manual = dict(
        db.execute(
            select(CashFlowPayment.cash_flow_entry_id, func.sum(CashFlowPayment.amount))
            .where(
                CashFlowPayment.cash_flow_entry_id.in_(entry_ids),
                CashFlowPayment.plan_id == plan.id,
                CashFlowPayment.is_auto_generated.is_(False),
            )
            .group_by(CashFlowPayment.cash_flow_entry_id)
        ).all()
    )
    return paid, manual


def _open_debt_committed(
    db: Session, user: User, plan: Plan, month_start: date
) -> dict[tuple[int, int], Decimal]:
    """Pendiente de deudas abiertas por mes: los pagos planificados manuales del plan
    descuentan capacidad en el mes de su planned_date, neteados contra los pagos reales
    del mismo mes (espejo de open_debt_monthly del timeline). Convertido."""
    rows = db.execute(
        select(CashFlowPayment, CashFlowEntry.currency_id)
        .join(CashFlowEntry, CashFlowEntry.id == CashFlowPayment.cash_flow_entry_id)
        .where(
            CashFlowEntry.user_id == user.id,
            CashFlowEntry.source_type == "deuda_abierta",
            or_(CashFlowPayment.plan_id.is_(None), CashFlowPayment.plan_id == plan.id),
            CashFlowPayment.is_auto_generated.is_(False),
        )
    ).all()
    buckets: dict[tuple[uuid.UUID, int, int], dict] = {}
    for p, currency_id in rows:
        d = p.planned_date or p.created_at.date()
        b = buckets.setdefault(
            (p.cash_flow_entry_id, d.year, d.month),
            {"planned": ZERO, "real": ZERO, "date": d, "currency_id": currency_id},
        )
        if p.plan_id is None:
            b["real"] += p.amount
        else:
            b["planned"] += p.amount
        b["date"] = min(b["date"], d)
    out: dict[tuple[int, int], Decimal] = {}
    for (_entry_id, y, mth), b in buckets.items():
        if date(y, mth, 1) < month_start:
            continue
        pending = b["planned"] - b["real"]
        if pending <= 0:
            continue
        out[(y, mth)] = out.get((y, mth), ZERO) + pending * _rate(db, b["currency_id"], b["date"])
    return out


@dataclass
class _OpenDebt:
    entry_id: uuid.UUID
    fx: Decimal
    outstanding: Decimal  # en moneda nativa de la deuda


def _load_open_debts(db: Session, user: User, plan: Plan, today: date) -> list[_OpenDebt]:
    """Deudas abiertas del usuario con saldo pendiente (monto − real − manual), más vieja
    primero. No se joinea obligations (la entry puede no tenerla)."""
    rows = list(
        db.execute(
            select(CashFlowEntry)
            .where(
                CashFlowEntry.user_id == user.id,
                CashFlowEntry.source_type == "deuda_abierta",
            )
            .order_by(CashFlowEntry.created_at.asc(), CashFlowEntry.id.asc())
        ).scalars()
    )
    if not rows:
        return []
    paid, manual = _payment_sums(db, [r.id for r in rows], plan)
    debts: list[_OpenDebt] = []
    for r in rows:
        outstanding = r.amount - paid.get(r.id, ZERO) - manual.get(r.id, ZERO)
        if outstanding <= 0:
            continue
        debts.append(_OpenDebt(entry_id=r.id, fx=_rate(db, r.currency_id, today), outstanding=outstanding))
    return debts


def _last_day(month: tuple[int, int]) -> date:
    y, m = month
    return date(y, m, calendar.monthrange(y, m)[1])


def _sweep_open_debts(
    db: Session, plan: Plan, open_debts: list[_OpenDebt], idle: Decimal, month: tuple[int, int]
) -> Decimal:
    """Vuelca `idle` (base convertida) a las deudas abiertas (más vieja primero), generando
    pagos auto datados el último día del mes. Devuelve el total pagado (base convertida)."""
    if idle <= 0:
        return ZERO
    planned = _last_day(month)
    total = ZERO
    for d in open_debts:
        if idle <= 0:
            break
        if d.outstanding <= 0:
            continue
        pay_conv = min(d.outstanding * d.fx, idle)
        pay_native = (pay_conv / d.fx).quantize(Q, rounding=ROUND_DOWN)
        if pay_native <= 0:
            continue
        db.add(
            CashFlowPayment(
                cash_flow_entry_id=d.entry_id, amount=pay_native, plan_id=plan.id,
                planned_date=planned, is_auto_generated=True,
            )
        )
        d.outstanding -= pay_native
        spent = pay_native * d.fx
        idle -= spent
        total += spent
    return total


def _load_entries(db: Session, user: User, plan: Plan, month_start: date) -> list[_Entry]:
    pm_ids = select(PlanMovement.id).where(PlanMovement.plan_id == plan.id)
    rows = list(
        db.execute(
            select(CashFlowEntry)
            .where(
                CashFlowEntry.user_id == user.id,
                CashFlowEntry.event_date.is_not(None),
                CashFlowEntry.event_date >= month_start,
                CashFlowEntry.source_type != "deuda_abierta",
                or_(
                    CashFlowEntry.source_type.notin_(_PLAN_TYPES),
                    CashFlowEntry.source_id.in_(pm_ids),
                ),
            )
            .order_by(CashFlowEntry.event_date.asc(), CashFlowEntry.id.asc())
        ).scalars()
    )
    paid, manual = _payment_sums(db, [r.id for r in rows], plan)
    return [
        _Entry(
            id=r.id, event_date=r.event_date, is_income=r.is_income,
            source_type=r.source_type, source_id=r.source_id, currency_id=r.currency_id,
            base_amount=r.amount,
            financing_rate=r.financing_rate or ZERO,
            overdue_rate=r.overdue_rate or ZERO,
            minimum_payment=r.minimum_payment if r.source_type == "tarjeta_credito" else None,
            paid_real=paid.get(r.id, ZERO),
            manual=manual.get(r.id, ZERO),
            fx=_rate(db, r.currency_id, r.event_date),
        )
        for r in rows
    ]


def _pending_income(entries: list[_Entry]) -> Decimal:
    total = ZERO
    for e in entries:
        if not e.is_income:
            continue
        eff = e.manual if e.manual > 0 else e.amount
        total += (eff - e.paid_real) * e.fx
    return total


def _spent(entries: list[_Entry]) -> Decimal:
    return sum((e.consumption() for e in entries if not e.is_income), ZERO)


def _allocate_month(
    entries: list[_Entry], capacity: Decimal, next_entries: list[_Entry], dial: Decimal,
    open_debt_next: Decimal = ZERO,
) -> None:
    expenses = [e for e in entries if not e.is_income and e.amount > 0]
    for e in expenses:
        e.decided = e.committed
    # paso 1: obligatorios (sin tasas) al total, siempre
    for e in expenses:
        if not e.has_rates:
            e.decided = max(e.decided, e.amount)
    # paso 2: mínimos (deudas con tasas: el total), siempre
    for e in expenses:
        if e.has_rates:
            e.decided = max(e.decided, min(e.minimum, e.amount))
    # paso 3: avalancha — cada peso extra ahorra tasa/12: va a la tasa mayor primero
    surplus = capacity - _spent(entries)
    if surplus <= 0:
        return
    candidates = sorted(
        (e for e in expenses if e.has_rates and e.saldo > 0),
        key=lambda e: (-e.financing_rate, e.event_date, str(e.id)),
    )
    for e in candidates:
        if surplus <= 0:
            break
        reserve = _lookahead_reserve(entries, next_entries, e.financing_rate * 2, dial, open_debt_next)
        budget = surplus - reserve
        if budget <= 0:
            continue
        pay = min(e.saldo * e.fx, budget)
        e.decided += (pay / e.fx).quantize(Q, rounding=ROUND_DOWN)  # nunca pasarse del sobrante
        surplus = capacity - _spent(entries)


def _carry_preview(entries: list[_Entry]) -> dict[tuple[uuid.UUID, int], Decimal]:
    """Arrastre por (tarjeta, moneda) con las decisiones tomadas hasta ahora."""
    out: dict[tuple[uuid.UUID, int], Decimal] = {}
    for e in entries:
        if e.is_income or not e.is_card or e.amount <= 0:
            continue
        payment = e.decided if e.decided > 0 else e.amount  # sin decisión: asume pago total
        c = monthly_carry(e.amount, payment, min(e.minimum, e.amount), e.financing_rate, e.overdue_rate)
        if c > 0:
            out[(e.source_id, e.currency_id)] = c
    return out


def _apply_carry(entries: list[_Entry], next_entries: list[_Entry]) -> None:
    carry = _carry_preview(entries)
    for n in next_entries:
        if n.is_card:
            cin = carry.get((n.source_id, n.currency_id))
            if cin:
                n.carry_in += cin


def _lookahead_terms(
    entries: list[_Entry], next_entries: list[_Entry], threshold: Decimal, dial: Decimal,
    open_debt_next: Decimal = ZERO,
) -> tuple[Decimal, Decimal]:
    """(demand, surplus) de M+1: demand = monto con tasa > threshold por encima del floor;
    surplus = caja standalone de M+1 antes de la avalancha discrecional (puede ser < 0)."""
    if not next_entries:
        return ZERO, ZERO
    carry = _carry_preview(entries)
    saved = [(n, n.carry_in) for n in next_entries]
    try:
        for n in next_entries:
            if n.is_card:
                n.carry_in += carry.get((n.source_id, n.currency_id), ZERO)
        surplus = _pending_income(next_entries) - dial - open_debt_next
        demand = ZERO
        for n in next_entries:
            if n.is_income or n.amount <= 0:
                continue
            if not n.has_rates:
                surplus -= max(ZERO, n.amount - n.paid_real) * n.fx
                continue
            floor = max(n.committed, min(n.minimum, n.amount))
            surplus -= max(ZERO, floor - n.paid_real) * n.fx
            if n.financing_rate > threshold:
                demand += max(ZERO, n.amount - floor) * n.fx
        return demand, surplus
    finally:
        for n, cin in saved:
            n.carry_in = cin


def _lookahead_reserve(
    entries: list[_Entry], next_entries: list[_Entry], threshold: Decimal, dial: Decimal,
    open_debt_next: Decimal = ZERO,
) -> Decimal:
    demand, surplus = _lookahead_terms(entries, next_entries, threshold, dial, open_debt_next)
    return max(ZERO, demand - max(ZERO, surplus))


def _reserve_next(
    entries: list[_Entry], next_entries: list[_Entry], dial: Decimal, open_debt_next: Decimal
) -> Decimal:
    """Lo que M+1 necesita recibir arrastrado para sostenerse: faltante de caja + demanda
    con tasa (umbral 0: el 0% de la deuda abierta cede ante cualquier tasa futura)."""
    demand, surplus = _lookahead_terms(entries, next_entries, ZERO, dial, open_debt_next)
    return max(ZERO, demand - max(ZERO, surplus)) + max(ZERO, -surplus)


def _seed_initial_carry(db: Session, user: User, plan: Plan, entries: list[_Entry], month_start: date) -> None:
    """Arrastre que viene de los meses anteriores al inicio de la simulación: recorre las
    series de tarjeta históricas con la regla de pago del timeline (planificado > real >
    total) y suma el arrastre resultante a la primera entry simulada de cada (tarjeta,
    moneda) — espejo de la cascada de get_timeline."""
    firsts: dict[tuple[uuid.UUID, int], _Entry] = {}
    for e in sorted((e for e in entries if e.is_card), key=lambda e: (e.event_date, str(e.id))):
        firsts.setdefault((e.source_id, e.currency_id), e)
    if not firsts:
        return
    past_rows = list(
        db.execute(
            select(CashFlowEntry)
            .where(
                CashFlowEntry.user_id == user.id,
                CashFlowEntry.source_type == "tarjeta_credito",
                CashFlowEntry.event_date.is_not(None),
                CashFlowEntry.event_date < month_start,
            )
            .order_by(CashFlowEntry.event_date.asc(), CashFlowEntry.id.asc())
        ).scalars()
    )
    if not past_rows:
        return
    paid, manual = _payment_sums(db, [r.id for r in past_rows], plan)

    series: dict[tuple[uuid.UUID, int], list[CashFlowEntry]] = {}
    for r in past_rows:
        series.setdefault((r.source_id, r.currency_id), []).append(r)

    for key, rows in series.items():
        cin = ZERO
        for r in rows:
            amount = r.amount + cin
            if cin > 0:
                minimum = (amount * PROJECTED_MINIMUM_RATE).quantize(Q, rounding=ROUND_HALF_UP)
            else:
                minimum = r.minimum_payment if r.minimum_payment is not None else amount
            planned = manual.get(r.id, ZERO)
            real = paid.get(r.id, ZERO)
            payment = planned if planned > 0 else real if real > 0 else amount
            cin = monthly_carry(amount, payment, minimum, r.financing_rate or ZERO, r.overdue_rate or ZERO)
        # sin entry simulada para esa (tarjeta, moneda) no hay dónde sembrar: el arrastre
        # se pierde en esta corrida (el CashFlowEngine densifica meses, así que es raro)
        if cin > 0 and key in firsts:
            firsts[key].carry_in += cin


def _materialize(db: Session, plan: Plan, entries: list[_Entry]) -> None:
    for e in entries:
        if e.is_income or e.amount <= 0 or e.decided <= 0:
            continue
        # fila solo si la decisión difiere de lo que el timeline asume sin filas (spec §8)
        needs_row = e.decided != e.amount or (ZERO < e.paid_real < e.decided)
        if not needs_row:
            continue
        amount = e.decided - e.manual
        if amount <= 0:
            continue
        db.add(
            CashFlowPayment(
                cash_flow_entry_id=e.id, amount=amount, plan_id=plan.id,
                planned_date=e.event_date, is_auto_generated=True,
            )
        )


def _require_plan(db: Session, user: User, plan_id: uuid.UUID) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    return plan


def _delete_auto_payments(db: Session, plan_id: uuid.UUID) -> None:
    """Borra los pagos auto-generados del plan. Sin commit (lo maneja quien llama)."""
    db.execute(
        delete(CashFlowPayment).where(
            CashFlowPayment.plan_id == plan_id,
            CashFlowPayment.is_auto_generated.is_(True),
        )
    )


def clear_planning(db: Session, user: User, plan_id: uuid.UUID) -> None:
    """Borra los pagos auto-generados del plan sin recalcular. Los manuales no se tocan."""
    plan = _require_plan(db, user, plan_id)
    _delete_auto_payments(db, plan.id)
    db.commit()


def run_planning(db: Session, user: User, plan_id: uuid.UUID, *, today: date | None = None) -> None:
    today = today or date.today()
    plan = _require_plan(db, user, plan_id)

    _delete_auto_payments(db, plan.id)

    month_start = today.replace(day=1)
    entries = _load_entries(db, user, plan, month_start)
    _seed_initial_carry(db, user, plan, entries, month_start)
    open_debt = _open_debt_committed(db, user, plan, month_start)
    open_debt_balances = _load_open_debts(db, user, plan, today)
    months = sorted({e.month for e in entries} | set(open_debt))
    by_month = {m: [e for e in entries if e.month == m] for m in months}

    dial = plan.dial_amount * _rate(db, plan.dial_currency_id, today)
    settings_row = db.get(UserFinancialSettings, user.id)
    monthly_need = settings_row.monthly_need_amount if settings_row is not None else None

    prev_balance: Decimal | None = None
    for idx, m in enumerate(months):
        month_entries = by_month[m]
        if prev_balance is None:  # primer mes >= actual = ancla del efectivo (igual timeline)
            available = _available_now(db, user, today)
            if m == (today.year, today.month):
                if monthly_need is not None:
                    remaining = monthly_need
                else:
                    days = calendar.monthrange(today.year, today.month)[1]
                    remaining = (dial * Decimal(days - (today.day - 1)) / Decimal(days)).quantize(
                        Q, rounding=ROUND_HALF_UP
                    )
            else:
                remaining = dial
        else:
            available = prev_balance
            remaining = dial

        capacity = available + _pending_income(month_entries) - remaining - open_debt.get(m, ZERO)
        next_entries = by_month[months[idx + 1]] if idx + 1 < len(months) else []
        open_debt_next = open_debt.get(months[idx + 1], ZERO) if idx + 1 < len(months) else ZERO
        _allocate_month(month_entries, capacity, next_entries, dial, open_debt_next)
        sobrante = capacity - _spent(month_entries)
        reserva = _reserve_next(month_entries, next_entries, dial, open_debt_next)
        idle = max(ZERO, sobrante - reserva)
        paid_open = _sweep_open_debts(db, plan, open_debt_balances, idle, m)
        prev_balance = sobrante - paid_open
        _apply_carry(month_entries, next_entries)

    _materialize(db, plan, entries)
    db.flush()
    db.commit()
