import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.user import User
from app.services.cash_flow.debts import materialize_debt
from app.services.cash_flow.expenses import materialize_expense
from app.services.cash_flow.open_debts import materialize_open_debt

OBLIGATION_SOURCE_TYPES = ("gasto", "deuda", "deuda_abierta")


def _get_owned(db: Session, user: User, obligation_id: uuid.UUID) -> Obligation:
    obligation = db.execute(
        select(Obligation).where(Obligation.id == obligation_id, Obligation.user_id == user.id)
    ).scalar_one_or_none()
    if obligation is None:
        raise AppError(ErrorCode.not_found)
    return obligation


def delete_obligation(db: Session, user: User, obligation_id: uuid.UUID) -> None:
    obligation = _get_owned(db, user, obligation_id)

    # check (a): sin hijas
    has_children = db.execute(
        select(Obligation.id).where(Obligation.origin_obligation_id == obligation.id).limit(1)
    ).first() is not None
    if has_children:
        raise AppError(ErrorCode.obligation_has_children)

    # check (b): sin pagos reales (plan_id IS NULL)
    has_real_payments = db.execute(
        select(CashFlowPayment.id)
        .join(CashFlowEntry, CashFlowEntry.id == CashFlowPayment.cash_flow_entry_id)
        .where(
            CashFlowEntry.source_type.in_(OBLIGATION_SOURCE_TYPES),
            CashFlowEntry.source_id == obligation.id,
            CashFlowPayment.plan_id.is_(None),
        )
        .limit(1)
    ).first() is not None
    if has_real_payments:
        raise AppError(ErrorCode.obligation_has_payments)

    # borrado orquestado: entries (sus pagos planificados caen por cascade) → la obligación
    db.execute(
        delete(CashFlowEntry).where(
            CashFlowEntry.source_type.in_(OBLIGATION_SOURCE_TYPES),
            CashFlowEntry.source_id == obligation.id,
        )
    )
    db.delete(obligation)
    db.commit()


def acknowledge_obligation(db: Session, user: User, obligation_id: uuid.UUID) -> Obligation:
    obligation = _get_owned(db, user, obligation_id)
    if obligation.review_findings == "[]":
        raise AppError(ErrorCode.obligation_has_no_findings)

    # update de 3 columnas; updated_at se preserva (reconocer no es cambio de negocio)
    db.execute(
        update(Obligation)
        .where(Obligation.id == obligation.id)
        .values(
            review_findings="[]",
            user_acknowledged_at=datetime.now(timezone.utc),
            is_ready=True,
            updated_at=obligation.updated_at,
        )
    )
    db.refresh(obligation)  # sincroniza el objeto (is_ready=true) antes de invocar el motor

    kind = db.get(ObligationType, obligation.obligation_type_id).obligation_kind
    if kind == "gasto":
        materialize_expense(db, obligation.id)
    elif kind == "deuda":
        materialize_debt(db, obligation.id)
    else:
        materialize_open_debt(db, obligation.id)

    db.commit()
    db.refresh(obligation)
    return obligation
