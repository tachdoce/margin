import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.income import Income
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


def _target_event_dates(income: Income, today: date, horizon: date) -> list[date]:
    """event_date de cada entry que el income debería tener. Vacío si está borrado."""
    month_start = today.replace(day=1)
    if income.deleted_at is not None:
        return []

    dates: list[date] = []
    if income.is_monthly_recurring:
        for y, m in _iter_months(today.year, today.month, horizon.year, horizon.month):
            ed = compute_event_date(y, m, income.payment_day, income.shift_weekends)
            if month_start <= ed <= horizon:
                dates.append(ed)
    else:
        y, m = income.first_income_date.year, income.first_income_date.month
        day = income.first_income_date.day
        for _ in range(income.total_months):
            ed = compute_event_date(y, m, day, income.shift_weekends)
            if month_start <= ed <= horizon:
                dates.append(ed)
            m += 1
            if m > 12:
                m, y = 1, y + 1
    return dates


def materialize_income(
    db: Session, income_id: uuid.UUID, *, today: date | None = None, horizon: date = HORIZON
) -> None:
    """(Re)materializa las cash_flow_entries de un income por UPSERT contra su clave lógica
    (año, mes, currency_id). No hace commit: la transacción la controla el caller."""
    if today is None:
        today = date.today()
    month_start = today.replace(day=1)

    income = db.execute(
        select(Income).where(Income.id == income_id).with_for_update()
    ).scalar_one_or_none()
    if income is None:
        return

    targets = _target_event_dates(income, today, horizon)

    existing = list(
        db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "ingreso",
                CashFlowEntry.source_id == income.id,
            )
        ).scalars()
    )
    by_key = {(e.event_date.year, e.event_date.month, e.currency_id): e for e in existing}

    target_keys: set[tuple[int, int, int]] = set()
    for ed in targets:
        key = (ed.year, ed.month, income.currency_id)
        target_keys.add(key)
        entry = by_key.get(key)
        if entry is not None:
            entry.amount = income.amount
            entry.event_date = ed
        else:
            db.add(
                CashFlowEntry(
                    user_id=income.user_id,
                    event_date=ed,
                    is_income=True,
                    amount=income.amount,
                    currency_id=income.currency_id,
                    source_type="ingreso",
                    source_id=income.id,
                )
            )

    # borrar las existentes fuera del objetivo: solo del mes actual en adelante (event_date >= month_start) sin pago real
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
            if e.event_date is not None and e.event_date >= month_start and e.id not in paid_ids:
                db.delete(e)

    db.flush()
