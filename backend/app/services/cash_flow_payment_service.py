import uuid
from datetime import date, datetime

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.schemas.cash_flow_payment import PaymentCreate, PaymentUpdate

PLAN_ENTRY_TYPES = {"plan_movimiento", "plan_movimiento_entrada"}


def _load_owned_entry(db: Session, user: User, entry_id: uuid.UUID) -> CashFlowEntry:
    entry = db.get(CashFlowEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    return entry


def _load_owned_plan(db: Session, user: User, plan_id: uuid.UUID) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    return plan


def _is_plan_entry(entry: CashFlowEntry) -> bool:
    return entry.source_type in PLAN_ENTRY_TYPES


def _entry_plan_id(db: Session, entry: CashFlowEntry) -> uuid.UUID | None:
    # solo tiene sentido para entries de plan: sube source_id -> plan_movements.plan_id
    pm = db.get(PlanMovement, entry.source_id)
    return pm.plan_id if pm else None


def _load_owned_payment(db: Session, entry: CashFlowEntry, payment_id: uuid.UUID) -> CashFlowPayment:
    payment = db.get(CashFlowPayment, payment_id)
    if payment is None or payment.cash_flow_entry_id != entry.id:
        raise AppError(ErrorCode.not_found)
    return payment


def create_payment(db: Session, user: User, entry_id: uuid.UUID, payload: PaymentCreate) -> CashFlowPayment:
    entry = _load_owned_entry(db, user, entry_id)

    # coherencia plan_id / planned_date: ambos o ninguno
    if (payload.plan_id is None) != (payload.planned_date is None):
        raise AppError(ErrorCode.planned_payment_incomplete)

    if payload.plan_id is not None:
        _load_owned_plan(db, user, payload.plan_id)

    # pagabilidad: la excepción es la entry de plan
    if payload.plan_id is None:
        # pago real: solo contra entries que NO son de plan
        if _is_plan_entry(entry):
            raise AppError(ErrorCode.entry_not_payable)
    else:
        # pago planificado: entry real -> ok; entry de plan -> mismo plan
        if _is_plan_entry(entry) and _entry_plan_id(db, entry) != payload.plan_id:
            raise AppError(ErrorCode.entry_not_payable)

    if payload.amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")

    payment = CashFlowPayment(
        cash_flow_entry_id=entry.id,
        amount=payload.amount,
        note=payload.note,
        plan_id=payload.plan_id,
        planned_date=payload.planned_date,
    )
    db.add(payment)
    db.flush()
    db.commit()
    db.refresh(payment)
    return payment


def _parse_month(month: str) -> date:
    try:
        return datetime.strptime(month, "%Y-%m").date().replace(day=1)
    except (ValueError, TypeError):
        raise AppError(ErrorCode.month_invalid)


def list_payments(
    db: Session, user: User, entry_id: uuid.UUID, plan_id: uuid.UUID | None, month: str | None
) -> list[CashFlowPayment]:
    if plan_id is None:
        raise AppError(ErrorCode.plan_id_required)
    month_start = _parse_month(month) if month is not None else None
    entry = _load_owned_entry(db, user, entry_id)
    _load_owned_plan(db, user, plan_id)

    stmt = select(CashFlowPayment).where(
        CashFlowPayment.cash_flow_entry_id == entry.id,
        (CashFlowPayment.plan_id.is_(None)) | (CashFlowPayment.plan_id == plan_id),
    )
    if month_start is not None:
        bucket = func.date_trunc(
            "month", func.coalesce(CashFlowPayment.planned_date, cast(CashFlowPayment.created_at, Date))
        )
        stmt = stmt.where(bucket == month_start)
    stmt = stmt.order_by(CashFlowPayment.created_at.desc())
    return list(db.execute(stmt).scalars())


def update_payment(
    db: Session, user: User, entry_id: uuid.UUID, payment_id: uuid.UUID, payload: PaymentUpdate
) -> CashFlowPayment:
    entry = _load_owned_entry(db, user, entry_id)
    payment = _load_owned_payment(db, entry, payment_id)

    fields = payload.model_fields_set
    if not fields & {"amount", "note", "planned_date"}:
        raise AppError(ErrorCode.empty_patch)

    if "amount" in fields:
        if payload.amount is None or payload.amount <= 0:
            raise AppError(ErrorCode.amount_invalid, field="amount")
        payment.amount = payload.amount

    if "note" in fields:
        payment.note = payload.note

    if "planned_date" in fields:
        if payment.plan_id is None:
            raise AppError(ErrorCode.planned_date_on_real_payment, field="planned_date")
        if payload.planned_date is None:
            raise AppError(ErrorCode.planned_date_invalid, field="planned_date")
        payment.planned_date = payload.planned_date

    db.flush()
    db.commit()
    db.refresh(payment)
    return payment


def delete_payment(db: Session, user: User, entry_id: uuid.UUID, payment_id: uuid.UUID) -> None:
    entry = _load_owned_entry(db, user, entry_id)
    payment = _load_owned_payment(db, entry, payment_id)
    db.delete(payment)
    db.commit()
