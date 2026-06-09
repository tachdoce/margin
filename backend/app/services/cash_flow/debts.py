import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.country import Country
from app.models.obligation import Obligation
from app.models.user import User
from app.services.cash_flow.date_utils import compute_event_date
from app.services.cash_flow.rates import effective_rate

HORIZON = date(2027, 12, 31)


def _target_event_dates(obligation: Obligation, today: date, horizon: date) -> list[date]:
    """event_date de cada cuota/evento que la deuda debería tener. Vacío si está cerrada."""
    month_start = today.replace(day=1)
    if obligation.is_closed:
        return []

    dates: list[date] = []
    if obligation.total_installments is not None:  # cronograma de cuotas
        if obligation.due_day is None:
            raise RuntimeError(
                f"materialize_debt: deuda con cronograma {obligation.id} sin due_day"
            )
        fdd = obligation.first_due_date
        y, m = fdd.year, fdd.month
        for _ in range(obligation.total_installments):
            ed = compute_event_date(y, m, obligation.due_day, obligation.shift_weekends)
            if month_start <= ed <= horizon:
                dates.append(ed)
            m += 1
            if m > 12:
                m, y = 1, y + 1
    else:  # pago único
        fdd = obligation.first_due_date
        ed = compute_event_date(fdd.year, fdd.month, fdd.day, obligation.shift_weekends)
        if month_start <= ed <= horizon:
            dates.append(ed)
    return dates


def materialize_debt(
    db: Session, obligation_id: uuid.UUID, *, today: date | None = None, horizon: date = HORIZON
) -> None:
    """(Re)materializa las cash_flow_entries de una obligación-deuda por UPSERT contra su clave lógica
    (año, mes, currency_id), congelando las tasas efectivas. Gate: is_ready False → no-op. No commit."""
    if today is None:
        today = date.today()
    month_start = today.replace(day=1)

    obligation = db.execute(
        select(Obligation).where(Obligation.id == obligation_id).with_for_update()
    ).scalar_one_or_none()
    if obligation is None:
        return
    if not obligation.is_ready:
        return  # gate: no-op silencioso

    targets = _target_event_dates(obligation, today, horizon)

    # tasas efectivas (iguales para todas las filas): una sola vez
    if obligation.financing_rate is not None or obligation.overdue_rate is not None:
        user = db.get(User, obligation.user_id)
        vat_rate = db.get(Country, user.country_code).vat_rate
    else:
        vat_rate = None
    fin_eff = effective_rate(obligation.financing_rate, obligation.rates_add_vat, vat_rate)
    over_eff = effective_rate(obligation.overdue_rate, obligation.rates_add_vat, vat_rate)

    existing = list(
        db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "deuda",
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
            entry.financing_rate = fin_eff
            entry.overdue_rate = over_eff
        else:
            db.add(
                CashFlowEntry(
                    user_id=obligation.user_id,
                    event_date=ed,
                    is_income=False,
                    amount=obligation.amount,
                    currency_id=obligation.currency_id,
                    financing_rate=fin_eff,
                    overdue_rate=over_eff,
                    source_type="deuda",
                    source_id=obligation.id,
                )
            )

    # borrar stale: solo del mes actual en adelante (event_date >= month_start) sin pago real; con pago real → raise.
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
            if e.event_date is not None and e.event_date >= month_start:
                if e.id in paid_ids:
                    raise RuntimeError(
                        f"materialize_debt: invariante violado, "
                        f"entry {e.id} con pago real quedó fuera del objetivo"
                    )
                db.delete(e)

    db.flush()
