import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.obligation import Obligation

RATE_THRESHOLD = 150


def _findings(obligation: Obligation) -> list[str]:
    """Codes de los chequeos que dispara la obligación (ordenados, sin duplicados)."""
    codes: list[str] = []
    fin = obligation.financing_rate
    over = obligation.overdue_rate

    if fin is not None and over is not None and over < fin:
        codes.append("overdue_lower_than_financing")
    if (fin is not None and fin > RATE_THRESHOLD) or (over is not None and over > RATE_THRESHOLD):
        codes.append("rate_above_threshold")

    return sorted(set(codes))


def review_obligation(db: Session, obligation_id: uuid.UUID) -> None:
    """Revisa la obligación y aplica la transición del ciclo de revisión: setea reviewed_at,
    review_findings, is_ready y resetea user_acknowledged_at si hay findings. No hace commit."""
    obligation = db.execute(
        select(Obligation).where(Obligation.id == obligation_id).with_for_update()
    ).scalar_one_or_none()
    if obligation is None:
        return

    findings = _findings(obligation)
    obligation.reviewed_at = datetime.now(timezone.utc)
    obligation.review_findings = json.dumps(findings)
    obligation.is_ready = len(findings) == 0
    if findings:
        obligation.user_acknowledged_at = None  # invalida una aceptación previa

    db.flush()
