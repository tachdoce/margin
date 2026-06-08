import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.schemas.plan import PlanCreate, PlanUpdate
from app.services.scoping import legal_tender_currency

DEFAULT_PLAN_NAME = "Mi plan actual"
GOAL_KINDS = ("ahorro_total",)


def _validate_goal(goal_kind: str | None, goal_amount: Decimal | None) -> None:
    """Objetivo todo-o-nada: ambos None (sin objetivo) o ambos válidos."""
    if goal_kind is None and goal_amount is None:
        return
    if goal_kind is None or goal_amount is None:
        raise AppError(ErrorCode.goal_invalid)
    if goal_kind not in GOAL_KINDS or goal_amount <= 0:
        raise AppError(ErrorCode.goal_invalid)


def create_default_plan(db: Session, user: User) -> Plan:
    """Crea el plan default del usuario (representa su realidad actual). No hace commit:
    la transacción la controla el caller (register_user)."""
    currency = legal_tender_currency(db, user)
    plan = Plan(
        user_id=user.id,
        name=DEFAULT_PLAN_NAME,
        is_default=True,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("0"),
        dial_currency_id=currency.id,
        goal_kind=None,
        goal_amount=None,
        goal_currency_id=None,
    )
    db.add(plan)
    return plan


def create_plan(db: Session, user: User, payload: PlanCreate) -> Plan:
    name = (payload.name or "").strip()
    if not name:
        raise AppError(ErrorCode.name_required, field="name")
    if payload.dial_amount is None or payload.dial_amount < 0:
        raise AppError(ErrorCode.dial_amount_invalid, field="dial_amount")
    _validate_goal(payload.goal_kind, payload.goal_amount)

    currency = legal_tender_currency(db, user)
    has_goal = payload.goal_kind is not None
    selected_at = datetime.now(timezone.utc) if payload.select_on_create else user.created_at

    plan = Plan(
        user_id=user.id,
        name=name,
        is_default=False,
        is_engine_generated=False,
        selected_at=selected_at,
        dial_amount=payload.dial_amount,
        dial_currency_id=currency.id,
        goal_kind=payload.goal_kind,
        goal_amount=payload.goal_amount,
        goal_currency_id=currency.id if has_goal else None,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def list_plans(db: Session, user: User) -> list[Plan]:
    return list(
        db.execute(
            select(Plan)
            .where(Plan.user_id == user.id)
            .order_by(Plan.selected_at.desc(), Plan.created_at.desc())
        ).scalars()
    )


def update_plan(db: Session, user: User, plan_id: uuid.UUID, payload: PlanUpdate) -> Plan:
    plan = db.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == user.id)
    ).scalar_one_or_none()
    if plan is None:
        raise AppError(ErrorCode.not_found)

    fields = payload.model_fields_set
    if not fields:
        raise AppError(ErrorCode.empty_patch)

    if "name" in fields and (payload.name is None or not payload.name.strip()):
        raise AppError(ErrorCode.name_required, field="name")
    if "dial_amount" in fields and (payload.dial_amount is None or payload.dial_amount < 0):
        raise AppError(ErrorCode.dial_amount_invalid, field="dial_amount")

    final_goal_kind = payload.goal_kind if "goal_kind" in fields else plan.goal_kind
    final_goal_amount = payload.goal_amount if "goal_amount" in fields else plan.goal_amount
    _validate_goal(final_goal_kind, final_goal_amount)

    if "name" in fields:
        plan.name = payload.name.strip()
    if "dial_amount" in fields:
        plan.dial_amount = payload.dial_amount
    if "goal_kind" in fields:
        plan.goal_kind = payload.goal_kind
    if "goal_amount" in fields:
        plan.goal_amount = payload.goal_amount
    plan.goal_currency_id = legal_tender_currency(db, user).id if final_goal_kind is not None else None

    db.commit()
    db.refresh(plan)
    return plan


def select_plan(db: Session, user: User, plan_id: uuid.UUID) -> Plan:
    plan = db.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == user.id)
    ).scalar_one_or_none()
    if plan is None:
        raise AppError(ErrorCode.not_found)

    # selected_at = now(); updated_at se preserva explícitamente (seleccionar es navegación, no
    # cambio de datos de negocio — pasar updated_at evita que onupdate=now() lo pise).
    db.execute(
        update(Plan)
        .where(Plan.id == plan.id)
        .values(selected_at=datetime.now(timezone.utc), updated_at=plan.updated_at)
    )
    db.commit()
    db.refresh(plan)
    return plan


def delete_plan(db: Session, user: User, plan_id: uuid.UUID) -> None:
    """Borrado orquestado del plan + sus movimientos + entries + pagos planificados. El default no se borra."""
    plan = db.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == user.id)
    ).scalar_one_or_none()
    if plan is None:
        raise AppError(ErrorCode.not_found)
    if plan.is_default:
        raise AppError(ErrorCode.default_plan_undeletable)

    # 1. pagos planificados del plan (incluso los imputados a entries reales)
    db.execute(delete(CashFlowPayment).where(CashFlowPayment.plan_id == plan.id))
    # 2. entries de los movimientos del plan
    movement_ids = select(PlanMovement.id).where(PlanMovement.plan_id == plan.id)
    db.execute(
        delete(CashFlowEntry).where(
            CashFlowEntry.source_type.in_(("plan_movimiento", "plan_movimiento_entrada")),
            CashFlowEntry.source_id.in_(movement_ids),
        )
    )
    # 3. movimientos
    db.execute(delete(PlanMovement).where(PlanMovement.plan_id == plan.id))
    # 4. el plan
    db.delete(plan)
    db.commit()
