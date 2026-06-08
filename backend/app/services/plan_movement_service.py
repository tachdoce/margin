import uuid
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.currency import Currency
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.schemas.plan_movement import PlanMovementCreate, PlanMovementUpdate
from app.services.cash_flow.plan_movements import materialize_plan_movement

MOVEMENT_KINDS = ("ingreso", "deuda_informal", "prestamo")
INCOME_FIELD = ("income_duration_months",)
INSTALLMENT_FIELDS = ("installment_amount", "installment_start_date", "total_installments")
RATE_FIELDS = ("financing_rate", "overdue_rate", "rates_add_vat")
OPTIONAL_FIELDS = INCOME_FIELD + INSTALLMENT_FIELDS + RATE_FIELDS


def _get_owned_plan(db: Session, user: User, plan_id: uuid.UUID) -> Plan:
    plan = db.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == user.id)
    ).scalar_one_or_none()
    if plan is None:
        raise AppError(ErrorCode.not_found)
    return plan


def _get_movement(db: Session, plan_id: uuid.UUID, movement_id: uuid.UUID) -> PlanMovement:
    movement = db.execute(
        select(PlanMovement).where(PlanMovement.id == movement_id, PlanMovement.plan_id == plan_id)
    ).scalar_one_or_none()
    if movement is None:
        raise AppError(ErrorCode.not_found)
    return movement


def _validate_currency(db: Session, user: User, currency_id: int | None) -> None:
    currency = db.get(Currency, currency_id) if currency_id is not None else None
    if currency is None or currency.country_code != user.country_code:
        raise AppError(ErrorCode.currency_not_available, field="currency_id")


def _check_foreign_fields(kind: str, present: dict) -> None:
    """`present` = campos opcionales con valor no-None que se van a aplicar. Un campo fuera del kind → error."""
    if kind == "ingreso":
        if any(f in present for f in INSTALLMENT_FIELDS + RATE_FIELDS):
            raise AppError(ErrorCode.movement_fields_invalid)
    elif kind == "deuda_informal":
        if any(f in present for f in OPTIONAL_FIELDS):
            raise AppError(ErrorCode.movement_fields_invalid)
    elif kind == "prestamo":
        # income_duration_months solo se acepta con valor 1 (el backend lo fija igual)
        if "income_duration_months" in present and present["income_duration_months"] != 1:
            raise AppError(ErrorCode.movement_fields_invalid)


def _validate_installments(amount: Decimal | None, start, total: int | None) -> None:
    if amount is None or start is None or total is None:
        raise AppError(ErrorCode.installments_invalid)
    if amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="installment_amount")
    if total < 1:
        raise AppError(ErrorCode.installments_invalid)


def create_movement(
    db: Session, user: User, plan_id: uuid.UUID, payload: PlanMovementCreate
) -> PlanMovement:
    plan = _get_owned_plan(db, user, plan_id)
    if plan.is_default:
        raise AppError(ErrorCode.default_plan_no_movements)
    if payload.kind not in MOVEMENT_KINDS:
        raise AppError(ErrorCode.kind_invalid, field="kind")
    _validate_currency(db, user, payload.currency_id)
    if payload.principal_amount is None or payload.principal_amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="principal_amount")

    present = {f: getattr(payload, f) for f in OPTIONAL_FIELDS if getattr(payload, f) is not None}
    _check_foreign_fields(payload.kind, present)

    is_loan = payload.kind == "prestamo"
    if is_loan:
        _validate_installments(payload.installment_amount, payload.installment_start_date, payload.total_installments)

    movement = PlanMovement(
        plan_id=plan.id,
        kind=payload.kind,
        currency_id=payload.currency_id,
        description=payload.description,
        principal_amount=payload.principal_amount,
        start_date=payload.start_date,
        income_duration_months=1 if is_loan else payload.income_duration_months,
        installment_amount=payload.installment_amount if is_loan else None,
        installment_start_date=payload.installment_start_date if is_loan else None,
        total_installments=payload.total_installments if is_loan else None,
        financing_rate=payload.financing_rate if is_loan else None,
        overdue_rate=payload.overdue_rate if is_loan else None,
        rates_add_vat=payload.rates_add_vat if payload.rates_add_vat is not None else True,
    )
    db.add(movement)
    db.flush()
    materialize_plan_movement(db, movement.id)
    db.commit()
    db.refresh(movement)
    return movement


def list_movements(db: Session, user: User, plan_id: uuid.UUID) -> list[PlanMovement]:
    _get_owned_plan(db, user, plan_id)
    return list(
        db.execute(
            select(PlanMovement)
            .where(PlanMovement.plan_id == plan_id)
            .order_by(PlanMovement.start_date.asc())
        ).scalars()
    )


def update_movement(
    db: Session, user: User, plan_id: uuid.UUID, movement_id: uuid.UUID, payload: PlanMovementUpdate
) -> PlanMovement:
    _get_owned_plan(db, user, plan_id)
    movement = _get_movement(db, plan_id, movement_id)

    fields = payload.model_fields_set - {"kind"}  # el kind no es editable
    if not fields:
        raise AppError(ErrorCode.empty_patch)

    # consistencia kind↔columnas sobre los campos presentes con valor no-None, contra el kind de la fila
    present = {
        f: getattr(payload, f)
        for f in OPTIONAL_FIELDS
        if f in payload.model_fields_set and getattr(payload, f) is not None
    }
    _check_foreign_fields(movement.kind, present)

    if "currency_id" in fields:
        _validate_currency(db, user, payload.currency_id)
    if "principal_amount" in fields and (payload.principal_amount is None or payload.principal_amount <= 0):
        raise AppError(ErrorCode.amount_invalid, field="principal_amount")
    if "installment_amount" in fields and payload.installment_amount is not None and payload.installment_amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="installment_amount")

    # aplicar los campos presentes (ya validados; los ajenos al kind fueron rechazados arriba)
    for f in fields:
        setattr(movement, f, getattr(payload, f))

    # estado final de préstamo: las cuotas deben quedar consistentes
    if movement.kind == "prestamo":
        _validate_installments(
            movement.installment_amount, movement.installment_start_date, movement.total_installments
        )

    db.flush()
    materialize_plan_movement(db, movement.id)
    db.commit()
    db.refresh(movement)
    return movement


def delete_movement(db: Session, user: User, plan_id: uuid.UUID, movement_id: uuid.UUID) -> None:
    """Borra el movimiento y sus cash_flow_entries (los pagos planificados caen por cascade). No corre el motor."""
    _get_owned_plan(db, user, plan_id)
    movement = _get_movement(db, plan_id, movement_id)

    db.execute(
        delete(CashFlowEntry).where(
            CashFlowEntry.source_type.in_(("plan_movimiento", "plan_movimiento_entrada")),
            CashFlowEntry.source_id == movement.id,
        )
    )
    db.delete(movement)
    db.commit()
