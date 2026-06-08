# Endpoints de planes (CRUD + select) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Los 5 endpoints del recurso `plans` (POST/GET/PATCH/DELETE + select), con su validación y el borrado orquestado, sin correr el engine.

**Architecture:** Router nuevo `app/routers/plans.py` (registrado en `main.py`) → `plan_service.py` (extendido). Schemas en `app/schemas/plan.py`. 5 error codes nuevos. La derivación de moneda se refactoriza a un helper `_legal_tender_currency` compartido con `create_default_plan`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, pytest. Python 3.13 (`backend/.venv`). Tests con `create_all`.

**Spec:** `docs/superpowers/specs/2026-06-08-plans-endpoints-design.md`.

**Git:** rama `feat/plans-endpoints`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/schemas/plan.py            # PlanCreate / PlanUpdate / PlanOut          (NUEVO)
backend/app/routers/plans.py           # router de los 5 endpoints                  (NUEVO)
backend/app/services/plan_service.py   # + helper + create/list/update/delete/select (MODIFICAR)
backend/app/core/errors.py             # + 5 error codes                            (MODIFICAR)
backend/app/main.py                    # registrar el router                        (MODIFICAR)
backend/tests/test_plans.py            # tests de los 5 endpoints                   (NUEVO)
```

---

## Task 1: POST + GET (schemas, errores, helper, router)

**Files:** Create `app/schemas/plan.py`, `app/routers/plans.py`, `tests/test_plans.py`; Modify `app/core/errors.py`, `app/services/plan_service.py`, `app/main.py`.

- [ ] **Step 1: Crear la rama**

```bash
cd /Users/tachone/proyectos/margin
git checkout -b feat/plans-endpoints
```

- [ ] **Step 2: Agregar los 5 error codes en `app/core/errors.py`**

Dentro de `class ErrorCode`, después de `income_not_deleted`:

```python
    name_required = (422, "El plan necesita un nombre.")
    dial_amount_invalid = (422, "El monto del dial debe ser mayor o igual a 0.")
    goal_invalid = (422, "El objetivo no es válido.")
    empty_patch = (422, "No hay cambios para aplicar.")
    default_plan_undeletable = (409, "El plan actual no se puede borrar.")
```

- [ ] **Step 3: Crear `app/schemas/plan.py`**

```python
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.plan import Plan


class PlanCreate(BaseModel):
    name: str
    dial_amount: Decimal
    goal_kind: str | None = None
    goal_amount: Decimal | None = None
    select_on_create: bool = False


class PlanUpdate(BaseModel):
    name: str | None = None
    dial_amount: Decimal | None = None
    goal_kind: str | None = None
    goal_amount: Decimal | None = None


class PlanOut(BaseModel):
    id: uuid.UUID
    name: str
    is_default: bool
    is_engine_generated: bool
    selected_at: datetime
    dial_amount: Decimal
    dial_currency_id: int
    goal_kind: str | None
    goal_amount: Decimal | None
    goal_currency_id: int | None

    @classmethod
    def from_model(cls, plan: Plan) -> "PlanOut":
        return cls(
            id=plan.id,
            name=plan.name,
            is_default=plan.is_default,
            is_engine_generated=plan.is_engine_generated,
            selected_at=plan.selected_at,
            dial_amount=plan.dial_amount,
            dial_currency_id=plan.dial_currency_id,
            goal_kind=plan.goal_kind,
            goal_amount=plan.goal_amount,
            goal_currency_id=plan.goal_currency_id,
        )
```

- [ ] **Step 4: Refactor + create/list en `app/services/plan_service.py`**

Reemplazar el contenido completo de `app/services/plan_service.py` por (mantiene `create_default_plan` igual, usando el helper nuevo; agrega `create_plan` y `list_plans`):

```python
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.currency import Currency
from app.models.plan import Plan
from app.models.user import User
from app.schemas.plan import PlanCreate, PlanUpdate

DEFAULT_PLAN_NAME = "Mi plan actual"
GOAL_KINDS = ("ahorro_total",)


def _legal_tender_currency(db: Session, user: User) -> Currency:
    return db.execute(
        select(Currency).where(
            Currency.country_code == user.country_code,
            Currency.is_legal_tender.is_(True),
        )
    ).scalars().first()


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
    currency = _legal_tender_currency(db, user)
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

    currency = _legal_tender_currency(db, user)
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
```

> Nota: este reemplazo importa `uuid`, `PlanUpdate` y demás que usarán las tasks 2 y 3 (así no se vuelve a tocar la cabecera). `auth_service` sigue importando `create_default_plan` igual.

- [ ] **Step 5: Crear `app/routers/plans.py` (POST + GET)**

```python
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.plan import PlanCreate, PlanOut, PlanUpdate
from app.services import plan_service

router = APIRouter(tags=["plans"])


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: PlanCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanOut:
    return PlanOut.from_model(plan_service.create_plan(db, user, payload))


@router.get("/plans", response_model=list[PlanOut])
def list_plans(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PlanOut]:
    return [PlanOut.from_model(p) for p in plan_service.list_plans(db, user)]
```

(El import de `PlanUpdate` queda listo para las tasks 2/3.)

- [ ] **Step 6: Registrar el router en `app/main.py`**

Cambiar el import `from app.routers import auth, bootstrap, countries, health, incomes` por:

```python
from app.routers import auth, bootstrap, countries, health, incomes, plans
```

Y agregar tras `app.include_router(incomes.router)`:

```python
app.include_router(plans.router)
```

- [ ] **Step 7: Escribir los tests de POST + GET en `backend/tests/test_plans.py`**

```python
from decimal import Decimal

from app.models.plan import Plan
from sqlalchemy import select


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_plan_sin_objetivo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    resp = client.post("/plans", json={"name": "Escenario sin préstamo", "dial_amount": "15000.00"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Escenario sin préstamo"
    assert body["is_default"] is False
    assert body["is_engine_generated"] is False
    assert body["dial_amount"] == "15000.00"
    assert body["dial_currency_id"] == 1
    assert body["goal_kind"] is None
    assert body["goal_amount"] is None
    assert body["goal_currency_id"] is None


def test_create_plan_con_objetivo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    resp = client.post(
        "/plans",
        json={"name": "Comprar auto", "dial_amount": "12000.00", "goal_kind": "ahorro_total", "goal_amount": "300000.00"},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["goal_kind"] == "ahorro_total"
    assert body["goal_amount"] == "300000.00"
    assert body["goal_currency_id"] == 1


def test_create_plan_select_on_create_queda_activo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    created = client.post(
        "/plans", json={"name": "Activo ya", "dial_amount": "10000.00", "select_on_create": True}, headers=headers
    ).json()
    listed = client.get("/plans", headers=headers).json()
    assert listed[0]["id"] == created["id"]  # el más nuevo selected_at queda primero


def test_create_plan_sin_select_no_queda_activo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    client.post("/plans", json={"name": "Inactivo", "dial_amount": "10000.00"}, headers=headers)
    listed = client.get("/plans", headers=headers).json()
    assert listed[0]["is_default"] is True  # el default sigue siendo el activo


def test_create_plan_name_required(client, db_session, seed_uy_currency):
    headers = _auth(client)
    resp = client.post("/plans", json={"name": "   ", "dial_amount": "10000.00"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "name_required"


def test_create_plan_dial_negativo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    resp = client.post("/plans", json={"name": "X", "dial_amount": "-1.00"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "dial_amount_invalid"


def test_create_plan_objetivo_a_medias(client, db_session, seed_uy_currency):
    headers = _auth(client)
    resp = client.post(
        "/plans", json={"name": "X", "dial_amount": "10000.00", "goal_kind": "ahorro_total"}, headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "goal_invalid"


def test_create_plan_requires_auth(client, db_session, seed_uy_currency):
    resp = client.post("/plans", json={"name": "X", "dial_amount": "10000.00"})
    assert resp.status_code == 401


def test_list_plans_incluye_default(client, db_session, seed_uy_currency):
    headers = _auth(client)
    listed = client.get("/plans", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["is_default"] is True


def test_list_plans_requires_auth(client, db_session, seed_uy_currency):
    assert client.get("/plans").status_code == 401
```

- [ ] **Step 8: Correr los tests y verificar que pasan**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_plans.py -v`
Expected: PASAN los 10 tests.

- [ ] **Step 9: Regresión + commit**

Run: `pytest -q` (Expected: todos verdes).

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/schemas/plan.py backend/app/routers/plans.py backend/app/services/plan_service.py backend/app/core/errors.py backend/app/main.py backend/tests/test_plans.py
git commit -m "feat(backend): POST y GET /plans"
```

---

## Task 2: PATCH + select

**Files:** Modify `app/services/plan_service.py`, `app/routers/plans.py`, `tests/test_plans.py`.

- [ ] **Step 1: Escribir los tests que fallan (al final de `tests/test_plans.py`)**

```python
def _create(client, headers, **over):
    body = {"name": "Escenario", "dial_amount": "12000.00"}
    body.update(over)
    return client.post("/plans", json=body, headers=headers).json()


def test_patch_renombra_y_dial(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    resp = client.patch(f"/plans/{plan['id']}", json={"name": "Nuevo", "dial_amount": "13500.00"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Nuevo"
    assert resp.json()["dial_amount"] == "13500.00"


def test_patch_fija_objetivo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    resp = client.patch(
        f"/plans/{plan['id']}", json={"goal_kind": "ahorro_total", "goal_amount": "500000.00"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["goal_kind"] == "ahorro_total"
    assert resp.json()["goal_currency_id"] == 1


def test_patch_quita_objetivo(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers, goal_kind="ahorro_total", goal_amount="500000.00")
    resp = client.patch(f"/plans/{plan['id']}", json={"goal_kind": None, "goal_amount": None}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["goal_kind"] is None and body["goal_amount"] is None and body["goal_currency_id"] is None


def test_patch_objetivo_a_medias(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    resp = client.patch(f"/plans/{plan['id']}", json={"goal_amount": "500000.00"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "goal_invalid"


def test_patch_empty(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    resp = client.patch(f"/plans/{plan['id']}", json={}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "empty_patch"


def test_patch_name_vacio(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    resp = client.patch(f"/plans/{plan['id']}", json={"name": "  "}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "name_required"


def test_patch_other_user_not_found(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan = _create(client, owner)
    other = _auth(client, email="other@b.com")
    resp = client.patch(f"/plans/{plan['id']}", json={"name": "X"}, headers=other)
    assert resp.status_code == 404


def test_select_mueve_al_primero(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)  # nace inactivo (default primero)
    assert client.get("/plans", headers=headers).json()[0]["is_default"] is True
    resp = client.post(f"/plans/{plan['id']}/select", headers=headers)
    assert resp.status_code == 200
    assert client.get("/plans", headers=headers).json()[0]["id"] == plan["id"]


def test_select_no_toca_updated_at(client, db_session, seed_uy_currency):
    import uuid as _uuid

    headers = _auth(client)
    plan = _create(client, headers)
    before = db_session.execute(select(Plan).where(Plan.id == _uuid.UUID(plan["id"]))).scalar_one().updated_at
    client.post(f"/plans/{plan['id']}/select", headers=headers)
    db_session.expire_all()
    after = db_session.execute(select(Plan).where(Plan.id == _uuid.UUID(plan["id"]))).scalar_one().updated_at
    assert before == after


def test_select_other_user_not_found(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan = _create(client, owner)
    other = _auth(client, email="other@b.com")
    assert client.post(f"/plans/{plan['id']}/select", headers=other).status_code == 404
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `pytest tests/test_plans.py -k "patch or select" -v`
Expected: FALLAN (404/405 o AttributeError — `update_plan`/`select_plan` y sus rutas no existen).

- [ ] **Step 3: Agregar `update_plan` y `select_plan` a `app/services/plan_service.py`**

Ampliar el import de SQLAlchemy: reemplazar `from sqlalchemy import select` por `from sqlalchemy import select, update`. Agregar al final del archivo:

```python
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
    plan.goal_currency_id = _legal_tender_currency(db, user).id if final_goal_kind is not None else None

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
```

- [ ] **Step 4: Agregar las rutas PATCH y select a `app/routers/plans.py`**

Al final del archivo:

```python
@router.patch("/plans/{plan_id}", response_model=PlanOut)
def update_plan(
    plan_id: uuid.UUID,
    payload: PlanUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanOut:
    return PlanOut.from_model(plan_service.update_plan(db, user, plan_id, payload))


@router.post("/plans/{plan_id}/select", response_model=PlanOut)
def select_plan(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanOut:
    return PlanOut.from_model(plan_service.select_plan(db, user, plan_id))
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `pytest tests/test_plans.py -k "patch or select" -v` (Expected: PASAN).

- [ ] **Step 6: Regresión + commit**

Run: `pytest -q` (Expected: todos verdes).

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/plan_service.py backend/app/routers/plans.py backend/tests/test_plans.py
git commit -m "feat(backend): PATCH /plans y POST /plans/{id}/select"
```

---

## Task 3: DELETE (borrado orquestado)

**Files:** Modify `app/services/plan_service.py`, `app/routers/plans.py`, `tests/test_plans.py`.

- [ ] **Step 1: Escribir los tests que fallan (al final de `tests/test_plans.py`)**

```python
def test_delete_default_409(client, db_session, seed_uy_currency):
    headers = _auth(client)
    default_id = client.get("/plans", headers=headers).json()[0]["id"]
    resp = client.delete(f"/plans/{default_id}", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "default_plan_undeletable"


def test_delete_no_default_borra(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan = _create(client, headers)
    assert client.delete(f"/plans/{plan['id']}", headers=headers).status_code == 204
    ids = [p["id"] for p in client.get("/plans", headers=headers).json()]
    assert plan["id"] not in ids


def test_delete_barre_movimientos_entries_y_pagos(client, db_session, seed_uy_currency):
    import uuid as _uuid

    from app.models.cash_flow_entry import CashFlowEntry
    from app.models.cash_flow_payment import CashFlowPayment
    from app.models.plan_movement import PlanMovement

    headers = _auth(client)
    plan = _create(client, headers)
    plan_uuid = _uuid.UUID(plan["id"])

    # sembrar a mano un plan_movement + una cash_flow_entry de plan + un pago planificado del plan
    mov = PlanMovement(
        plan_id=plan_uuid, kind="deuda_informal", currency_id=1, principal_amount=Decimal("30000.00"),
        start_date=__import__("datetime").date(2026, 8, 10), rates_add_vat=True,
    )
    db_session.add(mov)
    db_session.flush()
    entry = CashFlowEntry(
        user_id=db_session.execute(select(Plan).where(Plan.id == plan_uuid)).scalar_one().user_id,
        event_date=__import__("datetime").date(2026, 8, 10), is_income=False, amount=Decimal("30000.00"),
        currency_id=1, source_type="plan_movimiento", source_id=mov.id,
    )
    db_session.add(entry)
    db_session.flush()
    db_session.add(
        CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("1000.00"), plan_id=plan_uuid,
                        planned_date=__import__("datetime").date(2026, 8, 10))
    )
    db_session.flush()

    assert client.delete(f"/plans/{plan['id']}", headers=headers).status_code == 204

    db_session.expire_all()
    assert db_session.execute(select(PlanMovement).where(PlanMovement.plan_id == plan_uuid)).first() is None
    assert db_session.execute(select(CashFlowEntry).where(CashFlowEntry.source_id == mov.id)).first() is None
    assert db_session.execute(select(CashFlowPayment).where(CashFlowPayment.plan_id == plan_uuid)).first() is None


def test_delete_other_user_not_found(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan = _create(client, owner)
    other = _auth(client, email="other@b.com")
    assert client.delete(f"/plans/{plan['id']}", headers=other).status_code == 404
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `pytest tests/test_plans.py -k "delete" -v`
Expected: FALLAN (la ruta DELETE no existe → 404/405).

- [ ] **Step 3: Agregar `delete_plan` a `app/services/plan_service.py`**

Ampliar el import de SQLAlchemy: reemplazar `from sqlalchemy import select, update` por `from sqlalchemy import delete, select, update`. Agregar los imports de modelos junto a los demás `from app.models...`:

```python
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan_movement import PlanMovement
```

Agregar al final del archivo:

```python
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
```

- [ ] **Step 4: Agregar la ruta DELETE a `app/routers/plans.py`**

Al final del archivo:

```python
@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    plan_service.delete_plan(db, user, plan_id)
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `pytest tests/test_plans.py -k "delete" -v` (Expected: PASAN).

- [ ] **Step 6: Regresión + commit**

Run: `pytest -q` (Expected: todos verdes).

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/plan_service.py backend/app/routers/plans.py backend/tests/test_plans.py
git commit -m "feat(backend): DELETE /plans (borrado orquestado)"
```

---

## Notas de cierre

- Al terminar: los 5 endpoints de planes andan; el usuario puede crear/listar/editar/borrar/activar planes. Ningún endpoint corre el engine. Quedan los endpoints de `plan_movements` (slice siguiente) para colgar movimientos.
- **Cierre:** squash-merge de `feat/plans-endpoints` → un commit `feat: endpoints de planes (CRUD + select)` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** 5 error codes (§2) — Task 1 Step 2 ✓; schemas con PlanOut/from_model, plata string (§2) — Task 1 Step 3 ✓; helper `_legal_tender_currency` compartido (§2) — Task 1 Step 4 ✓; POST con validaciones + derivaciones + select_on_create (§3) — Task 1 Step 4 ✓; GET orden selected_at/created_at desc, array pelado (§4) — Task 1 Steps 4-5 ✓; PATCH estado final del objetivo + null para quitar + name/dial null rechazados (§5) — Task 2 Step 3 ✓; DELETE 4 pasos + default 409 (§6) — Task 3 Step 3 ✓; select sin tocar updated_at (§7) — Task 2 Step 3 (`update` con updated_at explícito) + test ✓; ningún endpoint corre engine — ninguna función llama al motor ✓.
- **Placeholders:** ninguno; código completo en cada step.
- **Consistencia de tipos:** `PlanOut.from_model`, firmas `create_plan/list_plans/update_plan/select_plan/delete_plan(db, user, ...)`, `_validate_goal`, `_legal_tender_currency` consistentes entre tasks; `model_fields_set` para PATCH; `select_on_create: bool = False`; los tests usan `seed_uy_currency` (registro crea el default) y consultas a `Plan/CashFlowEntry/CashFlowPayment/PlanMovement` con `uuid.UUID(...)` sobre el id string del JSON. La plata se asserta como string ("15000.00").
```
