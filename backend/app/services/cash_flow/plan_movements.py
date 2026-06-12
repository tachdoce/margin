import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.country import Country
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.services.cash_flow.date_utils import compute_event_date
from app.services.cash_flow.rates import effective_rate

# deuda: deuda en cuotas, sin entrada de capital (POST genérico).
# tarjetazo: igual que deuda, pero modela una compra de impulso desde una tarjeta;
#   se crea por POST .../movements/tarjetazos y se puede borrar en bloque
#   (DELETE .../movements/tarjetazos).
DEBT_KINDS = ("deuda", "tarjetazo")

HORIZON = date(2027, 12, 31)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _monthly_dates(start: date, count: int | None, horizon: date, *, shift: bool):
    """event_date de cada mes desde `start`, durante `count` meses (None = hasta el horizonte)."""
    y, m, day = start.year, start.month, start.day
    i = 0
    while (count is None or i < count) and (y, m) <= (horizon.year, horizon.month):
        yield compute_event_date(y, m, day, shift)
        y, m = _next_month(y, m)
        i += 1


def _target(source_type, event_date, is_income, amount, financing_rate=None, overdue_rate=None):
    return {
        "source_type": source_type,
        "event_date": event_date,
        "is_income": is_income,
        "amount": amount,
        "financing_rate": financing_rate,
        "overdue_rate": overdue_rate,
    }


def _target_entries(db: Session, movement: PlanMovement, user: User, today: date, horizon: date) -> list[dict]:
    targets: list[dict] = []
    kind = movement.kind

    if kind == "ingreso":
        if movement.income_duration_months == 1:
            ed = movement.start_date  # única: fecha literal exacta
            if today <= ed <= horizon:
                targets.append(_target("plan_movimiento", ed, True, movement.principal_amount))
        else:
            for ed in _monthly_dates(movement.start_date, movement.income_duration_months, horizon, shift=False):
                if today <= ed <= horizon:
                    targets.append(_target("plan_movimiento", ed, True, movement.principal_amount))

    elif kind == "deuda_informal":
        ed = movement.start_date  # literal exacta
        if today <= ed <= horizon:
            targets.append(_target("plan_movimiento", ed, False, movement.principal_amount))

    elif kind == "prestamo":
        # entrada de plata (1 fila, literal)
        ed = movement.start_date
        if today <= ed <= horizon:
            targets.append(_target("plan_movimiento_entrada", ed, True, movement.principal_amount))
        # cuotas (N filas, corren por finde, con tasa efectiva)
        vat_rate = db.get(Country, user.country_code).vat_rate
        fin = effective_rate(movement.financing_rate, movement.rates_add_vat, vat_rate)
        over = effective_rate(movement.overdue_rate, movement.rates_add_vat, vat_rate)
        for ed in _monthly_dates(movement.installment_start_date, movement.total_installments, horizon, shift=True):
            if today <= ed <= horizon:
                targets.append(
                    _target("plan_movimiento", ed, False, movement.installment_amount, fin, over)
                )

    elif kind in DEBT_KINDS:
        # como préstamo pero SIN la entrada de capital: solo cuotas de salida
        vat_rate = db.get(Country, user.country_code).vat_rate
        fin = effective_rate(movement.financing_rate, movement.rates_add_vat, vat_rate)
        over = effective_rate(movement.overdue_rate, movement.rates_add_vat, vat_rate)
        for ed in _monthly_dates(movement.installment_start_date, movement.total_installments, horizon, shift=True):
            if today <= ed <= horizon:
                targets.append(
                    _target("plan_movimiento", ed, False, movement.installment_amount, fin, over)
                )

    return targets


def materialize_plan_movement(
    db: Session, movement_id: uuid.UUID, *, today: date | None = None, horizon: date = HORIZON
) -> None:
    """(Re)materializa las cash_flow_entries de un plan_movements por UPSERT contra su clave lógica
    (source_type, año, mes, currency_id). No valida (confía en la fila) ni hace commit (lo controla el caller)."""
    if today is None:
        today = date.today()

    movement = db.execute(
        select(PlanMovement).where(PlanMovement.id == movement_id).with_for_update()
    ).scalar_one_or_none()
    if movement is None:
        return

    plan = db.get(Plan, movement.plan_id)
    user = db.get(User, plan.user_id)

    targets = _target_entries(db, movement, user, today, horizon)

    existing = list(
        db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_id == movement.id,
                CashFlowEntry.source_type.in_(("plan_movimiento", "plan_movimiento_entrada")),
            )
        ).scalars()
    )
    by_key = {(e.source_type, e.event_date.year, e.event_date.month, e.currency_id): e for e in existing}

    target_keys: set[tuple] = set()
    for t in targets:
        key = (t["source_type"], t["event_date"].year, t["event_date"].month, movement.currency_id)
        target_keys.add(key)
        entry = by_key.get(key)
        if entry is not None:
            entry.amount = t["amount"]
            entry.event_date = t["event_date"]
            entry.financing_rate = t["financing_rate"]
            entry.overdue_rate = t["overdue_rate"]
        else:
            db.add(
                CashFlowEntry(
                    user_id=plan.user_id,
                    event_date=t["event_date"],
                    is_income=t["is_income"],
                    amount=t["amount"],
                    currency_id=movement.currency_id,
                    financing_rate=t["financing_rate"],
                    overdue_rate=t["overdue_rate"],
                    source_type=t["source_type"],
                    source_id=movement.id,
                )
            )

    # borrar las existentes fuera del objetivo, solo futuras (las entries de plan no tienen pagos reales)
    for key, e in by_key.items():
        if key not in target_keys and e.event_date is not None and e.event_date >= today:
            db.delete(e)

    db.flush()
