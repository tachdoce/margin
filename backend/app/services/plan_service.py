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
from app.schemas.plan import PlanCopyRequest, PlanCreate, PlanUpdate
from app.services.cash_flow.plan_movements import materialize_plan_movement
from app.services.cash_flow_payment_service import PLAN_ENTRY_TYPES
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


def copy_plan(db: Session, user: User, plan_id: uuid.UUID, payload: PlanCopyRequest) -> Plan:
    """Copia profunda de un plan excluyendo lo is_auto_generated. Plan nuevo (no seleccionado) +
    movements re-materializados + pagos planificados re-enganchados. Transacción única."""
    source = db.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == user.id)
    ).scalar_one_or_none()
    if source is None:
        raise AppError(ErrorCode.not_found)

    name = (payload.name or "").strip()
    if not name:
        raise AppError(ErrorCode.name_required, field="name")

    new_plan = Plan(
        user_id=user.id,
        name=name,
        is_default=False,
        is_engine_generated=False,
        selected_at=user.created_at,  # no seleccionado (igual que create_plan sin select)
        dial_amount=source.dial_amount,
        dial_currency_id=source.dial_currency_id,
        goal_kind=source.goal_kind,
        goal_amount=source.goal_amount,
        goal_currency_id=source.goal_currency_id,
    )
    db.add(new_plan)
    db.flush()

    # movements no-auto: copiar + re-materializar
    movement_map: dict[uuid.UUID, uuid.UUID] = {}
    source_movements = db.execute(
        select(PlanMovement)
        .where(PlanMovement.plan_id == source.id, PlanMovement.is_auto_generated.is_(False))
        .order_by(PlanMovement.created_at)
    ).scalars().all()
    for m in source_movements:
        new_m = PlanMovement(
            plan_id=new_plan.id,
            kind=m.kind,
            currency_id=m.currency_id,
            description=m.description,
            principal_amount=m.principal_amount,
            start_date=m.start_date,
            income_duration_months=m.income_duration_months,
            installment_amount=m.installment_amount,
            installment_start_date=m.installment_start_date,
            total_installments=m.total_installments,
            financing_rate=m.financing_rate,
            overdue_rate=m.overdue_rate,
            rates_add_vat=m.rates_add_vat,
            is_auto_generated=False,
        )
        db.add(new_m)
        db.flush()
        movement_map[m.id] = new_m.id
        materialize_plan_movement(db, new_m.id)

    # índice de entries nuevas por (movement_nuevo, source_type, año, mes, currency)
    new_entries: dict[tuple, uuid.UUID] = {}
    if movement_map:
        for e in db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_id.in_(movement_map.values()),
                CashFlowEntry.source_type.in_(PLAN_ENTRY_TYPES),
            )
        ).scalars():
            new_entries[(e.source_id, e.source_type, e.event_date.year, e.event_date.month, e.currency_id)] = e.id

    # pagos planificados no-auto: copiar con re-enganche/descarte
    source_payments = db.execute(
        select(CashFlowPayment).where(
            CashFlowPayment.plan_id == source.id,
            CashFlowPayment.is_auto_generated.is_(False),
        )
    ).scalars().all()
    entry_ids = {p.cash_flow_entry_id for p in source_payments}
    entries_by_id = {
        e.id: e
        for e in db.execute(
            select(CashFlowEntry).where(CashFlowEntry.id.in_(entry_ids))
        ).scalars()
    } if entry_ids else {}
    for p in source_payments:
        entry = entries_by_id.get(p.cash_flow_entry_id)
        if entry is None:
            continue
        if entry.source_type in PLAN_ENTRY_TYPES:
            new_m_id = movement_map.get(entry.source_id)
            if new_m_id is None:
                continue  # el movement era auto-generado: no está en la copia
            target_id = new_entries.get(
                (new_m_id, entry.source_type, entry.event_date.year, entry.event_date.month, entry.currency_id)
            )
            if target_id is None:
                continue  # entry pasada: la re-materialización hoy→horizonte no la regeneró
        else:
            target_id = entry.id  # entry real/compartida: misma entry
        db.add(
            CashFlowPayment(
                cash_flow_entry_id=target_id,
                amount=p.amount,
                note=p.note,
                plan_id=new_plan.id,
                planned_date=p.planned_date,
            )
        )

    db.commit()
    db.refresh(new_plan)
    return new_plan
