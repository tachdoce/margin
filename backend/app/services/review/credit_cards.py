import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement

CLOSING_DAY_CHANGE_THRESHOLD = 4


def _latest_statement_closing_day(db: Session, credit_card_id: uuid.UUID) -> int | None:
    """Día del closing_date del último resumen (mayor issue_year, luego issue_month) de la tarjeta.
    None si la tarjeta no tiene resúmenes."""
    closing_date = db.execute(
        select(CreditCardStatement.closing_date)
        .where(CreditCardStatement.credit_card_id == credit_card_id)
        .order_by(CreditCardStatement.issue_year.desc(), CreditCardStatement.issue_month.desc())
        .limit(1)
    ).scalar_one_or_none()
    return closing_date.day if closing_date is not None else None


def _findings(db: Session, card: CreditCard) -> list[str]:
    """Codes de los chequeos de la tarjeta (ordenados, sin duplicados). Las dos reglas son mutuamente
    excluyentes según created_at == updated_at (recién creada vs existente)."""
    codes: list[str] = []

    if card.created_at == card.updated_at:
        # recién creada: el closing_day se infirió del primer resumen; pedir confirmación.
        codes.append("closing_day_inferred")
    else:
        # existente: ¿el último resumen muestra un día de cierre distinto del vigente?
        statement_day = _latest_statement_closing_day(db, card.id)
        if (
            statement_day is not None
            and abs(statement_day - card.closing_day) > CLOSING_DAY_CHANGE_THRESHOLD
        ):
            codes.append("closing_day_changed")

    return sorted(set(codes))


def review_credit_card(db: Session, credit_card_id: uuid.UUID) -> None:
    """Revisa la tarjeta y aplica la transición del ciclo de revisión: setea reviewed_at, review_findings,
    is_ready y resetea user_acknowledged_at si hay findings. No hace commit."""
    card = db.execute(
        select(CreditCard).where(CreditCard.id == credit_card_id).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        return

    findings = _findings(db, card)
    card.reviewed_at = datetime.now(timezone.utc)
    card.review_findings = json.dumps(findings)
    card.is_ready = len(findings) == 0
    if findings:
        card.user_acknowledged_at = None  # invalida una aceptación previa

    db.flush()
