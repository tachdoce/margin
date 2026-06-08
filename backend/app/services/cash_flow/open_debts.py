import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.obligation import Obligation


def materialize_open_debt(db: Session, obligation_id: uuid.UUID) -> None:
    """(Re)materializa la única cash_flow_entries (atemporal, event_date NULL) de una obligación
    deuda_abierta. Gate: is_ready False → no-op. Nunca borra. No hace commit (lo controla el caller)."""
    obligation = db.execute(
        select(Obligation).where(Obligation.id == obligation_id).with_for_update()
    ).scalar_one_or_none()
    if obligation is None:
        return
    if not obligation.is_ready:
        return  # gate: no-op silencioso

    entry = db.execute(
        select(CashFlowEntry).where(
            CashFlowEntry.source_type == "deuda_abierta",
            CashFlowEntry.source_id == obligation.id,
        )
    ).scalar_one_or_none()

    if entry is not None:
        entry.amount = obligation.amount
        entry.currency_id = obligation.currency_id
    else:
        db.add(
            CashFlowEntry(
                user_id=obligation.user_id,
                event_date=None,
                is_income=False,
                amount=obligation.amount,
                currency_id=obligation.currency_id,
                financing_rate=None,
                overdue_rate=None,
                source_type="deuda_abierta",
                source_id=obligation.id,
            )
        )

    db.flush()
