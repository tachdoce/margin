import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.institution import Institution
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.user import User
from app.schemas.debt import DebtCreate, DebtUpdate
from app.services.cash_flow.debts import materialize_debt
from app.services.cash_flow.open_debts import materialize_open_debt
from app.services.obligation_common import (
    validate_amount,
    validate_description,
    validate_due_day,
    validate_payment_config,
)
from app.services.review.obligations import review_obligation
from app.services.scoping import require_user_currency

DEBT_KINDS = ("deuda", "deuda_abierta")
SCHEDULE_FIELDS = ("first_due_date", "total_installments", "due_day")


# --- validadores específicos de deudas ---

def _require_debt_type(db: Session, obligation_type_id: int | None) -> ObligationType:
    ot = db.get(ObligationType, obligation_type_id) if obligation_type_id is not None else None
    if ot is None or ot.obligation_kind not in DEBT_KINDS:
        raise AppError(ErrorCode.debt_type_invalid, field="obligation_type_id")
    if ot.obligation_kind == "deuda_abierta" and ot.code != "informal":
        raise AppError(ErrorCode.debt_type_invalid, field="obligation_type_id")
    return ot


def _validate_institution(db: Session, user: User, institution_id: int | None) -> None:
    inst = db.get(Institution, institution_id) if institution_id is not None else None
    if inst is None or inst.country_code != user.country_code:
        raise AppError(ErrorCode.institution_invalid, field="institution_id")


def _validate_rate(rate, field: str) -> None:
    if rate is not None and rate < 0:
        raise AppError(ErrorCode.rates_negative, field=field)


def _validate_deuda_form(due_day, total_installments, first_due_date) -> None:
    if first_due_date is None:
        raise AppError(ErrorCode.debt_requires_schedule_or_date, field="first_due_date")
    if total_installments is not None:  # cronograma
        if total_installments < 1:
            raise AppError(ErrorCode.installments_invalid, field="total_installments")
        if due_day is None:
            raise AppError(ErrorCode.debt_schedule_requires_due_day, field="due_day")
    else:  # pago único
        if due_day is not None:
            raise AppError(ErrorCode.one_time_debt_inconsistent, field="due_day")


def _validate_open_debt_form(due_day, total_installments, first_due_date, financing_rate, overdue_rate) -> None:
    if any(v is not None for v in (due_day, total_installments, first_due_date, financing_rate, overdue_rate)):
        raise AppError(ErrorCode.open_debt_inconsistent)


def _has_payments(db: Session, obligation_id: uuid.UUID) -> bool:
    return db.execute(
        select(CashFlowPayment.id)
        .join(CashFlowEntry, CashFlowEntry.id == CashFlowPayment.cash_flow_entry_id)
        .where(CashFlowEntry.source_type == "deuda", CashFlowEntry.source_id == obligation_id)
        .limit(1)
    ).first() is not None


def _debt_query(user: User):
    return (
        select(Obligation)
        .join(ObligationType, ObligationType.id == Obligation.obligation_type_id)
        .where(Obligation.user_id == user.id, ObligationType.obligation_kind.in_(DEBT_KINDS))
    )


def _run_engines(db: Session, obligation: Obligation, kind: str) -> None:
    review_obligation(db, obligation.id)
    if kind == "deuda":
        materialize_debt(db, obligation.id)
    else:
        materialize_open_debt(db, obligation.id)


def create_debt(db: Session, user: User, payload: DebtCreate) -> Obligation:
    ot = _require_debt_type(db, payload.obligation_type_id)
    kind = ot.obligation_kind
    require_user_currency(db, user, payload.currency_id)
    description = validate_description(payload.description)
    validate_amount(payload.amount)
    rule = payload.payment_rule or "ninguno"
    validate_payment_config(
        kind, payment_rule=rule, priority=payload.priority,
        monthly_paydown_amount=payload.monthly_paydown_amount,
        priority_open_debt=payload.priority_open_debt,
    )

    if kind == "deuda":
        if payload.institution_id is not None:
            _validate_institution(db, user, payload.institution_id)
        validate_due_day(payload.due_day)
        _validate_rate(payload.financing_rate, "financing_rate")
        _validate_rate(payload.overdue_rate, "overdue_rate")
        _validate_deuda_form(payload.due_day, payload.total_installments, payload.first_due_date)
        obligation = Obligation(
            user_id=user.id,
            obligation_type_id=payload.obligation_type_id,
            payment_rule=rule,
            priority=payload.priority,
            monthly_paydown_amount=None,
            priority_open_debt=None,
            institution_id=payload.institution_id,
            description=description,
            is_monthly_recurring=False,
            due_day=payload.due_day,
            currency_id=payload.currency_id,
            amount=payload.amount,
            total_installments=payload.total_installments,
            first_due_date=payload.first_due_date,
            financing_rate=payload.financing_rate,
            overdue_rate=payload.overdue_rate,
            rates_add_vat=payload.rates_add_vat if payload.rates_add_vat is not None else True,
            shift_weekends=payload.shift_weekends if payload.shift_weekends is not None else False,
            origin_obligation_id=None,
            is_closed=False,
            reviewed_at=None,
            review_findings="[]",
            user_acknowledged_at=None,
            is_ready=False,
        )
    else:  # deuda_abierta: institution_id/rates_add_vat/fechas/cuotas/tasas ignorados o NULL
        _validate_open_debt_form(
            payload.due_day, payload.total_installments, payload.first_due_date,
            payload.financing_rate, payload.overdue_rate,
        )
        obligation = Obligation(
            user_id=user.id,
            obligation_type_id=payload.obligation_type_id,
            payment_rule=rule,
            priority=None,
            monthly_paydown_amount=payload.monthly_paydown_amount,
            priority_open_debt=payload.priority_open_debt,
            institution_id=None,
            description=description,
            is_monthly_recurring=False,
            due_day=None,
            currency_id=payload.currency_id,
            amount=payload.amount,
            total_installments=None,
            first_due_date=None,
            financing_rate=None,
            overdue_rate=None,
            rates_add_vat=False,
            shift_weekends=False,
            origin_obligation_id=None,
            is_closed=False,
            reviewed_at=None,
            review_findings="[]",
            user_acknowledged_at=None,
            is_ready=False,
        )

    db.add(obligation)
    db.flush()
    _run_engines(db, obligation, kind)
    db.commit()
    db.refresh(obligation)
    return obligation


def list_debts(db: Session, user: User) -> list[Obligation]:
    return list(db.execute(_debt_query(user).order_by(Obligation.created_at.desc())).scalars())


def update_debt(db: Session, user: User, obligation_id: uuid.UUID, payload: DebtUpdate) -> Obligation:
    obligation = db.execute(_debt_query(user).where(Obligation.id == obligation_id)).scalar_one_or_none()
    if obligation is None:
        raise AppError(ErrorCode.not_found)
    kind = db.get(ObligationType, obligation.obligation_type_id).obligation_kind

    fields = payload.model_fields_set

    if "obligation_type_id" in fields:
        if kind == "deuda_abierta":
            raise AppError(ErrorCode.debt_type_invalid, field="obligation_type_id")
        new_type = _require_debt_type(db, payload.obligation_type_id)
        if new_type.obligation_kind != kind:
            raise AppError(ErrorCode.debt_type_invalid, field="obligation_type_id")
    if "currency_id" in fields:
        require_user_currency(db, user, payload.currency_id)
    if "description" in fields:
        validate_description(payload.description)
    if "amount" in fields:
        validate_amount(payload.amount)
    if "institution_id" in fields and payload.institution_id is not None:
        _validate_institution(db, user, payload.institution_id)
    if "due_day" in fields:
        validate_due_day(payload.due_day)
    if "financing_rate" in fields:
        _validate_rate(payload.financing_rate, "financing_rate")
    if "overdue_rate" in fields:
        _validate_rate(payload.overdue_rate, "overdue_rate")
    for f in ("rates_add_vat", "shift_weekends", "is_closed"):
        if f in fields and getattr(payload, f) is None:
            raise AppError(ErrorCode.field_not_nullable, field=f)

    # bloqueo de cronograma con pagos (solo deuda)
    changing_schedule = any(
        f in fields and getattr(payload, f) != getattr(obligation, f) for f in SCHEDULE_FIELDS
    )
    if changing_schedule and _has_payments(db, obligation.id):
        raise AppError(ErrorCode.debt_schedule_locked)

    # aplicar patch (en deuda_abierta, institution_id y rates_add_vat se ignoran)
    for f in fields:
        if kind == "deuda_abierta" and f in ("institution_id", "rates_add_vat", "obligation_type_id"):
            continue
        value = getattr(payload, f)
        if f == "description":
            value = value.strip()
        setattr(obligation, f, value)

    # validación del combo de prioridad sobre el estado ya mergeado
    if any(f in fields for f in ("payment_rule", "priority", "monthly_paydown_amount", "priority_open_debt")):
        validate_payment_config(
            kind, payment_rule=obligation.payment_rule, priority=obligation.priority,
            monthly_paydown_amount=obligation.monthly_paydown_amount,
            priority_open_debt=obligation.priority_open_debt,
        )

    # consistencia post-merge por kind
    if kind == "deuda":
        _validate_deuda_form(obligation.due_day, obligation.total_installments, obligation.first_due_date)
    else:
        _validate_open_debt_form(
            obligation.due_day, obligation.total_installments, obligation.first_due_date,
            obligation.financing_rate, obligation.overdue_rate,
        )

    db.flush()
    _run_engines(db, obligation, kind)
    db.commit()
    db.refresh(obligation)
    return obligation
