import calendar
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.credit_card import CreditCard
from app.models.staging_credit_card import StagingCreditCard

DUE_DATE_FUTURE_DAYS = 60
DUE_DATE_OLD_MONTHS = 12


def _months_ago(d: date, months: int) -> date:
    """`d` menos `months` meses, con clamp de día (ej. 31/3 - 1m -> 28/2)."""
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _findings(db: Session, staging: StagingCreditCard, today: date) -> list[str]:
    """Codes de los chequeos que dispara la madre (ordenados, sin duplicados). Cada regla con su
    guarda de NULL: la madre entra incompleta."""
    codes: list[str] = []

    closing = staging.closing_date
    due = staging.due_date

    if closing is not None and due is not None and closing > due:
        codes.append("closing_after_due")
    if due is not None and due > today + timedelta(days=DUE_DATE_FUTURE_DAYS):
        codes.append("due_date_in_future")
    if due is not None and due < _months_ago(today, DUE_DATE_OLD_MONTHS):
        codes.append("due_date_too_old")

    rates = (
        staging.financing_rate_local,
        staging.overdue_rate_local,
        staging.financing_rate_usd,
        staging.overdue_rate_usd,
    )
    if any(r is None for r in rates) or staging.rates_add_vat is None:
        codes.append("rates_not_updated")

    if staging.institution_id is not None and staging.card_network_id is not None:
        # incluye soft-deleted: el promote reactiva una tarjeta borrada en vez de crear otra.
        exists = db.execute(
            select(CreditCard.id).where(
                CreditCard.user_id == staging.user_id,
                CreditCard.institution_id == staging.institution_id,
                CreditCard.card_network_id == staging.card_network_id,
            )
        ).first()
        if exists is None:
            codes.append("new_card")

    return sorted(set(codes))


def review_staging_credit_card(
    db: Session, staging_credit_card_id: uuid.UUID, *, today: date | None = None
) -> None:
    """Revisa la madre del staging y aplica la transición del ciclo de revisión: setea reviewed_at,
    review_findings, is_ready y resetea user_acknowledged_at si hay findings. No hace commit."""
    if today is None:
        today = date.today()

    staging = db.execute(
        select(StagingCreditCard)
        .where(StagingCreditCard.id == staging_credit_card_id)
        .with_for_update()
    ).scalar_one_or_none()
    if staging is None:
        return

    findings = _findings(db, staging, today)
    staging.reviewed_at = datetime.now(timezone.utc)
    staging.review_findings = json.dumps(findings)
    staging.is_ready = len(findings) == 0
    if findings:
        staging.user_acknowledged_at = None  # invalida una aceptación previa

    db.flush()
