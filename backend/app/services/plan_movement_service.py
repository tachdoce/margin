import calendar
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.institution import Institution
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.schemas.plan_movement import PlanMovementCreate, PlanMovementUpdate, TarjetazoCreate
from app.services.cash_flow.plan_movements import DEBT_KINDS, materialize_plan_movement
from app.services.credit_card_service import _require_card
from app.services.scoping import require_user_currency

MOVEMENT_KINDS = ("ingreso", "deuda_informal", "prestamo", "deuda")
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
    elif kind in DEBT_KINDS:
        if any(f in present for f in INCOME_FIELD):
            raise AppError(ErrorCode.movement_fields_invalid)


def _validate_installments(amount: Decimal | None, start, total: int | None) -> None:
    if amount is None or start is None or total is None:
        raise AppError(ErrorCode.installments_invalid)
    if amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="installment_amount")
    if total < 1:
        raise AppError(ErrorCode.installments_invalid)


def _first_payment_date(closing_day: int, due_day: int, today: date) -> date:
    """Fecha del primer pago de una compra hecha hoy: entra al cierre de este mes
    si hoy <= closing_day, si no al del mes siguiente; vence el mismo mes del cierre
    si due_day >= closing_day, si no el mes siguiente."""
    last = calendar.monthrange(today.year, today.month)[1]
    closing_this = date(today.year, today.month, min(closing_day, last))
    if today <= closing_this:
        cy, cm = today.year, today.month
    else:
        cy, cm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    if due_day >= closing_day:
        dy, dm = cy, cm
    else:
        dy, dm = (cy + 1, 1) if cm == 12 else (cy, cm + 1)
    dlast = calendar.monthrange(dy, dm)[1]
    return date(dy, dm, min(due_day, dlast))


def create_movement(
    db: Session, user: User, plan_id: uuid.UUID, payload: PlanMovementCreate
) -> PlanMovement:
    plan = _get_owned_plan(db, user, plan_id)
    if plan.is_default:
        raise AppError(ErrorCode.default_plan_no_movements)
    if payload.kind not in MOVEMENT_KINDS:
        raise AppError(ErrorCode.kind_invalid, field="kind")
    require_user_currency(db, user, payload.currency_id)

    is_loan = payload.kind == "prestamo"
    is_debt = payload.kind in DEBT_KINDS
    uses_installments = is_loan or is_debt

    if not is_debt:
        if payload.principal_amount is None or payload.principal_amount <= 0:
            raise AppError(ErrorCode.amount_invalid, field="principal_amount")
        if payload.start_date is None:
            raise AppError(ErrorCode.movement_fields_invalid)

    present = {f: getattr(payload, f) for f in OPTIONAL_FIELDS if getattr(payload, f) is not None}
    _check_foreign_fields(payload.kind, present)

    if uses_installments:
        _validate_installments(payload.installment_amount, payload.installment_start_date, payload.total_installments)

    movement = PlanMovement(
        plan_id=plan.id,
        kind=payload.kind,
        currency_id=payload.currency_id,
        description=payload.description,
        principal_amount=Decimal(0) if is_debt else payload.principal_amount,
        start_date=payload.installment_start_date if is_debt else payload.start_date,
        income_duration_months=(1 if is_loan else (None if is_debt else payload.income_duration_months)),
        installment_amount=payload.installment_amount if uses_installments else None,
        installment_start_date=payload.installment_start_date if uses_installments else None,
        total_installments=payload.total_installments if uses_installments else None,
        financing_rate=payload.financing_rate if uses_installments else None,
        overdue_rate=payload.overdue_rate if uses_installments else None,
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
        require_user_currency(db, user, payload.currency_id)
    # en las deudas el principal es fijo en 0 (no entra capital): no se valida ni se aplica
    if (
        "principal_amount" in fields
        and movement.kind not in DEBT_KINDS
        and (payload.principal_amount is None or payload.principal_amount <= 0)
    ):
        raise AppError(ErrorCode.amount_invalid, field="principal_amount")
    if "installment_amount" in fields and payload.installment_amount is not None and payload.installment_amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="installment_amount")

    # aplicar los campos presentes (ya validados; los ajenos al kind fueron rechazados arriba)
    for f in fields:
        setattr(movement, f, getattr(payload, f))

    # estado final con cuotas (préstamo y deudas): deben quedar consistentes
    if movement.kind == "prestamo" or movement.kind in DEBT_KINDS:
        _validate_installments(
            movement.installment_amount, movement.installment_start_date, movement.total_installments
        )
    # en las deudas, start_date sigue al installment_start_date y el principal queda en 0
    if movement.kind in DEBT_KINDS:
        movement.start_date = movement.installment_start_date
        movement.principal_amount = Decimal(0)

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


def create_tarjetazo(
    db: Session, user: User, plan_id: uuid.UUID, payload: TarjetazoCreate, today: date | None = None
) -> PlanMovement:
    # Decisiones de diseño (simulación rápida, snapshot desacoplado de la tarjeta):
    # - No se chequea card.is_ready: el tarjetazo copia las tasas tal cual para simular ya,
    #   aunque la tarjeta no esté revisada.
    # - El primer pago se deriva de closing_day/due_day; el corrimiento por finde de la
    #   materialización podría, en teoría, dejar la 1ra cuota antes de `today`, pero las
    #   emisoras no dan cierre > 26, así que la fecha nunca cae tan cerca de fin de mes.
    if today is None:
        today = date.today()
    plan = _get_owned_plan(db, user, plan_id)
    if plan.is_default:
        raise AppError(ErrorCode.default_plan_no_movements)

    currency = require_user_currency(db, user, payload.currency_id)
    if not currency.allowed_in_credit_card:
        raise AppError(ErrorCode.currency_not_available, field="currency_id")

    card = _require_card(db, user, payload.credit_card_id)

    first_payment = _first_payment_date(card.closing_day, card.due_day, today)
    _validate_installments(payload.installment_amount, first_payment, payload.total_installments)

    if currency.is_legal_tender:
        fin, over = card.financing_rate_local, card.overdue_rate_local
    else:
        fin, over = card.financing_rate_usd, card.overdue_rate_usd
    institution = db.get(Institution, card.institution_id)

    movement = PlanMovement(
        plan_id=plan.id,
        kind="tarjetazo",
        currency_id=payload.currency_id,
        description=institution.name,
        principal_amount=Decimal(0),
        start_date=first_payment,
        income_duration_months=None,
        installment_amount=payload.installment_amount,
        installment_start_date=first_payment,
        total_installments=payload.total_installments,
        financing_rate=fin,
        overdue_rate=over,
        rates_add_vat=card.rates_add_vat,
    )
    db.add(movement)
    db.flush()
    materialize_plan_movement(db, movement.id, today=today)
    db.commit()
    db.refresh(movement)
    return movement


def delete_tarjetazos(db: Session, user: User, plan_id: uuid.UUID) -> int:
    """Borra todos los plan_movements kind=tarjetazo del plan y sus cash_flow_entries.
    Devuelve la cantidad borrada. No corre el motor."""
    _get_owned_plan(db, user, plan_id)
    ids = list(
        db.execute(
            select(PlanMovement.id).where(
                PlanMovement.plan_id == plan_id, PlanMovement.kind == "tarjetazo"
            )
        ).scalars()
    )
    if not ids:
        return 0
    db.execute(
        delete(CashFlowEntry).where(
            CashFlowEntry.source_type.in_(("plan_movimiento", "plan_movimiento_entrada")),
            CashFlowEntry.source_id.in_(ids),
        )
    )
    db.execute(delete(PlanMovement).where(PlanMovement.id.in_(ids)))
    db.commit()
    return len(ids)
