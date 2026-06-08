import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.services.cash_flow.date_utils import compute_event_date

HORIZON = date(2027, 12, 31)


def _iter_months(start_year: int, start_month: int, end_year: int, end_month: int):
    """(año, mes) desde (start) hasta (end) inclusive."""
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _target_event_dates(obligation: Obligation, today: date, horizon: date) -> list[date]:
    """event_date de cada entry que el gasto debería tener. Vacío si está cerrado."""
    if obligation.is_closed:
        return []

    dates: list[date] = []
    if obligation.is_monthly_recurring:
        for y, m in _iter_months(today.year, today.month, horizon.year, horizon.month):
            ed = compute_event_date(y, m, obligation.due_day, obligation.shift_weekends)
            if today <= ed <= horizon:
                dates.append(ed)
    else:
        fdd = obligation.first_due_date
        ed = compute_event_date(fdd.year, fdd.month, fdd.day, obligation.shift_weekends)
        if today <= ed <= horizon:
            dates.append(ed)
    return dates


def materialize_expense(
    db: Session, obligation_id: uuid.UUID, *, today: date | None = None, horizon: date = HORIZON
) -> None:
    """(Re)materializa las cash_flow_entries de una obligación-gasto por UPSERT contra su clave lógica
    (año, mes, currency_id). Gate: si is_ready es False, no-op. No hace commit (lo controla el caller)."""
    if today is None:
        today = date.today()

    obligation = db.execute(
        select(Obligation).where(Obligation.id == obligation_id).with_for_update()
    ).scalar_one_or_none()
    if obligation is None:
        return
    if not obligation.is_ready:
        return  # gate: no-op silencioso (no materializa, no borra)

    targets = _target_event_dates(obligation, today, horizon)

    existing = list(
        db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "gasto",
                CashFlowEntry.source_id == obligation.id,
            )
        ).scalars()
    )
    by_key = {(e.event_date.year, e.event_date.month, e.currency_id): e for e in existing}

    target_keys: set[tuple[int, int, int]] = set()
    for ed in targets:
        key = (ed.year, ed.month, obligation.currency_id)
        target_keys.add(key)
        entry = by_key.get(key)
        if entry is not None:
            entry.amount = obligation.amount
            entry.event_date = ed
        else:
            db.add(
                CashFlowEntry(
                    user_id=obligation.user_id,
                    event_date=ed,
                    is_income=False,
                    amount=obligation.amount,
                    currency_id=obligation.currency_id,
                    source_type="gasto",
                    source_id=obligation.id,
                )
            )

    # borrar las existentes fuera del objetivo: solo futuras (event_date >= today).
    # Si una futura stale tiene pago REAL (plan_id IS NULL) → no se borra: raise (rollback).
    stale = [e for key, e in by_key.items() if key not in target_keys]
    if stale:
        paid_ids = set(
            db.execute(
                select(CashFlowPayment.cash_flow_entry_id).where(
                    CashFlowPayment.cash_flow_entry_id.in_([e.id for e in stale]),
                    CashFlowPayment.plan_id.is_(None),
                )
            ).scalars()
        )
        for e in stale:
            if e.event_date is not None and e.event_date >= today:
                if e.id in paid_ids:
                    raise RuntimeError(
                        f"materialize_expense: invariante violado, "
                        f"entry {e.id} con pago real quedó fuera del objetivo"
                    )
                db.delete(e)

    db.flush()
