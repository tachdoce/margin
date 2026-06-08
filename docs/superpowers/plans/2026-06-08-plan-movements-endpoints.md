# Endpoints de `plan_movements` (CRUD) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Los 4 endpoints de `plan_movements` (POST/GET/PATCH/DELETE bajo `/plans/{id}/movements`), con la validación kind↔columnas, cableando el motor `materialize_plan_movement`.

**Architecture:** Router nuevo `app/routers/plan_movements.py` → servicio nuevo `app/services/plan_movement_service.py`. Schemas en `app/schemas/plan_movement.py`. 4 error codes nuevos. POST/PATCH corren el motor; DELETE orquesta el borrado. Validación kind↔columnas en un helper compartido.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, pytest. Python 3.13 (`backend/.venv`). Tests con `create_all`.

**Spec:** `docs/superpowers/specs/2026-06-08-plan-movements-endpoints-design.md`.

**Git:** rama `feat/plan-movements-endpoints`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/schemas/plan_movement.py            # Create / Update / Out          (NUEVO)
backend/app/routers/plan_movements.py           # 4 endpoints                    (NUEVO)
backend/app/services/plan_movement_service.py   # validación + CRUD + motor      (NUEVO)
backend/app/core/errors.py                      # + 4 error codes                (MODIFICAR)
backend/app/main.py                             # registrar router               (MODIFICAR)
backend/tests/test_plan_movements.py            # tests                          (NUEVO)
```

---

## Task 1: POST + GET (schemas, errores, validación, router)

**Files:** Create `app/schemas/plan_movement.py`, `app/services/plan_movement_service.py`, `app/routers/plan_movements.py`, `tests/test_plan_movements.py`; Modify `app/core/errors.py`, `app/main.py`.

- [ ] **Step 1: Crear la rama**

```bash
cd /Users/tachone/proyectos/margin
git checkout -b feat/plan-movements-endpoints
```

- [ ] **Step 2: Agregar los 4 error codes en `app/core/errors.py`**

Dentro de `class ErrorCode`, después de `default_plan_undeletable`:

```python
    default_plan_no_movements = (409, "El plan actual no admite movimientos. Creá un plan nuevo para simular escenarios.")
    kind_invalid = (422, "Tipo de movimiento no válido.")
    installments_invalid = (422, "Las cuotas no son válidas.")
    movement_fields_invalid = (422, "Los datos del movimiento no coinciden con su tipo.")
```

- [ ] **Step 3: Crear `app/schemas/plan_movement.py`**

```python
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.plan_movement import PlanMovement


class PlanMovementCreate(BaseModel):
    kind: str
    currency_id: int
    description: str | None = None
    principal_amount: Decimal
    start_date: date
    income_duration_months: int | None = None
    installment_amount: Decimal | None = None
    installment_start_date: date | None = None
    total_installments: int | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool | None = None


class PlanMovementUpdate(BaseModel):
    kind: str | None = None  # se ignora (el kind no es editable)
    currency_id: int | None = None
    description: str | None = None
    principal_amount: Decimal | None = None
    start_date: date | None = None
    income_duration_months: int | None = None
    installment_amount: Decimal | None = None
    installment_start_date: date | None = None
    total_installments: int | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool | None = None


class PlanMovementOut(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    kind: str
    currency_id: int
    description: str | None
    principal_amount: Decimal
    start_date: date
    income_duration_months: int | None
    installment_amount: Decimal | None
    installment_start_date: date | None
    total_installments: int | None
    financing_rate: Decimal | None
    overdue_rate: Decimal | None
    rates_add_vat: bool

    @classmethod
    def from_model(cls, m: PlanMovement) -> "PlanMovementOut":
        return cls(
            id=m.id,
            plan_id=m.plan_id,
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
        )
```

- [ ] **Step 4: Crear `app/services/plan_movement_service.py` (helpers + create + list)**

```python
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
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
```

- [ ] **Step 5: Crear `app/routers/plan_movements.py` (POST + GET)**

```python
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.plan_movement import PlanMovementCreate, PlanMovementOut, PlanMovementUpdate
from app.services import plan_movement_service

router = APIRouter(tags=["plan_movements"])


@router.post(
    "/plans/{plan_id}/movements", response_model=PlanMovementOut, status_code=status.HTTP_201_CREATED
)
def create_movement(
    plan_id: uuid.UUID,
    payload: PlanMovementCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanMovementOut:
    return PlanMovementOut.from_model(plan_movement_service.create_movement(db, user, plan_id, payload))


@router.get("/plans/{plan_id}/movements", response_model=list[PlanMovementOut])
def list_movements(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PlanMovementOut]:
    return [PlanMovementOut.from_model(m) for m in plan_movement_service.list_movements(db, user, plan_id)]
```

(El import de `PlanMovementUpdate` queda listo para la Task 2.)

- [ ] **Step 6: Registrar el router en `app/main.py`**

Cambiar `from app.routers import auth, bootstrap, countries, health, incomes, plans` por:

```python
from app.routers import auth, bootstrap, countries, health, incomes, plan_movements, plans
```

Y agregar tras `app.include_router(plans.router)`:

```python
app.include_router(plan_movements.router)
```

- [ ] **Step 7: Escribir los tests de POST + GET en `backend/tests/test_plan_movements.py`**

```python
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _plan(client, headers, **over):
    body = {"name": "Escenario", "dial_amount": "12000.00"}
    body.update(over)
    return client.post("/plans", json=body, headers=headers).json()["id"]


def _default_plan_id(client, headers):
    plans = client.get("/plans", headers=headers).json()
    return next(p["id"] for p in plans if p["is_default"])


def _ingreso(**over):
    body = {"kind": "ingreso", "currency_id": 1, "principal_amount": "45000.00", "start_date": "2026-07-05"}
    body.update(over)
    return body


def _prestamo(**over):
    body = {
        "kind": "prestamo",
        "currency_id": 1,
        "principal_amount": "200000.00",
        "start_date": "2026-07-01",
        "installment_amount": "10500.00",
        "installment_start_date": "2026-08-01",
        "total_installments": 24,
        "financing_rate": "72.00",
        "overdue_rate": "85.00",
        "rates_add_vat": True,
    }
    body.update(over)
    return body


def test_create_ingreso(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_ingreso(income_duration_months=None), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "ingreso"
    assert body["installment_amount"] is None
    assert body["principal_amount"] == "45000.00"


def test_create_deuda_informal(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(
        f"/plans/{plan_id}/movements",
        json={"kind": "deuda_informal", "currency_id": 1, "principal_amount": "30000.00", "start_date": "2026-08-10"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "deuda_informal"


def test_create_prestamo_fija_income_duration_1(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_prestamo(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "prestamo"
    assert body["income_duration_months"] == 1
    assert body["total_installments"] == 24


def test_create_materializa_entries(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    movement = client.post(f"/plans/{plan_id}/movements", json=_prestamo(), headers=headers).json()
    entries = db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_id == uuid.UUID(movement["id"]))
    ).scalars().all()
    assert len(entries) >= 1  # la entrada + cuotas futuras


def test_create_default_plan_409(client, db_session, seed_uy_currency):
    headers = _auth(client)
    default_id = _default_plan_id(client, headers)
    resp = client.post(f"/plans/{default_id}/movements", json=_ingreso(), headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "default_plan_no_movements"


def test_create_kind_invalid(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_ingreso(kind="otro"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "kind_invalid"


def test_create_principal_invalido(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_ingreso(principal_amount="0.00"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "amount_invalid"


def test_create_campo_de_otro_kind(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    # ingreso con un campo de cuotas -> movement_fields_invalid
    resp = client.post(
        f"/plans/{plan_id}/movements", json=_ingreso(installment_amount="100.00"), headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "movement_fields_invalid"


def test_create_prestamo_sin_total_installments(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    body = _prestamo()
    del body["total_installments"]
    resp = client.post(f"/plans/{plan_id}/movements", json=body, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "installments_invalid"


def test_create_currency_no_disponible(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_ingreso(currency_id=999), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "currency_not_available"


def test_create_other_user_404(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan_id = _plan(client, owner)
    other = _auth(client, email="other@b.com")
    resp = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=other)
    assert resp.status_code == 404


def test_create_requires_auth(client, db_session, seed_uy_currency):
    assert client.post("/plans/00000000-0000-0000-0000-000000000000/movements", json=_ingreso()).status_code == 401


def test_list_movements_ordenado(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    client.post(f"/plans/{plan_id}/movements", json=_ingreso(start_date="2026-09-05"), headers=headers)
    client.post(f"/plans/{plan_id}/movements", json=_ingreso(start_date="2026-07-05"), headers=headers)
    listed = client.get(f"/plans/{plan_id}/movements", headers=headers).json()
    assert [m["start_date"] for m in listed] == ["2026-07-05", "2026-09-05"]


def test_list_default_vacio(client, db_session, seed_uy_currency):
    headers = _auth(client)
    default_id = _default_plan_id(client, headers)
    assert client.get(f"/plans/{default_id}/movements", headers=headers).json() == []


def test_list_other_user_404(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan_id = _plan(client, owner)
    other = _auth(client, email="other@b.com")
    assert client.get(f"/plans/{plan_id}/movements", headers=other).status_code == 404
```

- [ ] **Step 8: Correr los tests y verificar que pasan**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_plan_movements.py -v`
Expected: PASAN los 15 tests.

- [ ] **Step 9: Regresión + commit**

Run: `pytest -q` (Expected: todos verdes).

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/schemas/plan_movement.py backend/app/services/plan_movement_service.py backend/app/routers/plan_movements.py backend/app/core/errors.py backend/app/main.py backend/tests/test_plan_movements.py
git commit -m "feat(backend): POST y GET /plans/{id}/movements"
```

---

## Task 2: PATCH

**Files:** Modify `app/services/plan_movement_service.py`, `app/routers/plan_movements.py`, `tests/test_plan_movements.py`.

- [ ] **Step 1: Escribir los tests que fallan (al final de `tests/test_plan_movements.py`)**

```python
def _create_prestamo(client, headers, plan_id):
    return client.post(f"/plans/{plan_id}/movements", json=_prestamo(), headers=headers).json()


def test_patch_edita_principal(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=headers).json()
    resp = client.patch(
        f"/plans/{plan_id}/movements/{mov['id']}", json={"principal_amount": "50000.00"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["principal_amount"] == "50000.00"


def test_patch_ajusta_cuota_rematerializa(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = _create_prestamo(client, headers, plan_id)
    resp = client.patch(
        f"/plans/{plan_id}/movements/{mov['id']}", json={"installment_amount": "11000.00"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["installment_amount"] == "11000.00"
    cuotas = db_session.execute(
        select(CashFlowEntry).where(
            CashFlowEntry.source_id == uuid.UUID(mov["id"]), CashFlowEntry.source_type == "plan_movimiento"
        )
    ).scalars().all()
    assert all(c.amount == Decimal("11000.00") for c in cuotas)


def test_patch_ignora_kind(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=headers).json()
    resp = client.patch(
        f"/plans/{plan_id}/movements/{mov['id']}", json={"kind": "prestamo", "description": "x"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "ingreso"  # no cambió


def test_patch_campo_de_otro_kind(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=headers).json()
    resp = client.patch(
        f"/plans/{plan_id}/movements/{mov['id']}", json={"installment_amount": "100.00"}, headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "movement_fields_invalid"


def test_patch_empty(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=headers).json()
    resp = client.patch(f"/plans/{plan_id}/movements/{mov['id']}", json={}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "empty_patch"


def test_patch_other_user_404(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan_id = _plan(client, owner)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=owner).json()
    other = _auth(client, email="other@b.com")
    resp = client.patch(f"/plans/{plan_id}/movements/{mov['id']}", json={"description": "x"}, headers=other)
    assert resp.status_code == 404
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `pytest tests/test_plan_movements.py -k "patch" -v`
Expected: FALLAN (la ruta PATCH no existe → 404/405).

- [ ] **Step 3: Agregar `update_movement` a `app/services/plan_movement_service.py`**

Al final del archivo:

```python
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
```

- [ ] **Step 4: Agregar la ruta PATCH a `app/routers/plan_movements.py`**

Al final del archivo:

```python
@router.patch("/plans/{plan_id}/movements/{movement_id}", response_model=PlanMovementOut)
def update_movement(
    plan_id: uuid.UUID,
    movement_id: uuid.UUID,
    payload: PlanMovementUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanMovementOut:
    return PlanMovementOut.from_model(
        plan_movement_service.update_movement(db, user, plan_id, movement_id, payload)
    )
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `pytest tests/test_plan_movements.py -k "patch" -v` (Expected: PASAN).

- [ ] **Step 6: Regresión + commit**

Run: `pytest -q` (Expected: todos verdes).

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/plan_movement_service.py backend/app/routers/plan_movements.py backend/tests/test_plan_movements.py
git commit -m "feat(backend): PATCH /plans/{id}/movements/{movement_id}"
```

---

## Task 3: DELETE (borrado orquestado)

**Files:** Modify `app/services/plan_movement_service.py`, `app/routers/plan_movements.py`, `tests/test_plan_movements.py`.

- [ ] **Step 1: Escribir los tests que fallan (al final de `tests/test_plan_movements.py`)**

```python
def test_delete_borra_movimiento_y_entries(client, db_session, seed_uy_currency):
    from app.models.cash_flow_payment import CashFlowPayment
    from app.models.plan_movement import PlanMovement

    headers = _auth(client)
    plan_id = _plan(client, headers)
    mov = _create_prestamo(client, headers, plan_id)
    mov_uuid = uuid.UUID(mov["id"])

    # imputar un pago planificado a una entry del movimiento
    entry = db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_id == mov_uuid)
    ).scalars().first()
    db_session.add(
        CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("100.00"), plan_id=uuid.UUID(plan_id),
                        planned_date=entry.event_date)
    )
    db_session.flush()

    assert client.delete(f"/plans/{plan_id}/movements/{mov['id']}", headers=headers).status_code == 204

    db_session.expire_all()
    assert db_session.get(PlanMovement, mov_uuid) is None
    assert db_session.execute(select(CashFlowEntry).where(CashFlowEntry.source_id == mov_uuid)).first() is None
    assert db_session.execute(
        select(CashFlowPayment).where(CashFlowPayment.cash_flow_entry_id == entry.id)
    ).first() is None


def test_delete_missing_404(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.delete(
        f"/plans/{plan_id}/movements/00000000-0000-0000-0000-000000000000", headers=headers
    )
    assert resp.status_code == 404


def test_delete_other_user_404(client, db_session, seed_uy_currency):
    owner = _auth(client, email="owner@b.com")
    plan_id = _plan(client, owner)
    mov = client.post(f"/plans/{plan_id}/movements", json=_ingreso(), headers=owner).json()
    other = _auth(client, email="other@b.com")
    assert client.delete(f"/plans/{plan_id}/movements/{mov['id']}", headers=other).status_code == 404
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `pytest tests/test_plan_movements.py -k "delete" -v`
Expected: FALLAN (la ruta DELETE no existe → 404/405).

- [ ] **Step 3: Agregar `delete_movement` a `app/services/plan_movement_service.py`**

Ampliar el import de SQLAlchemy: reemplazar `from sqlalchemy import select` por `from sqlalchemy import delete, select`. Agregar el import del modelo junto a los demás:

```python
from app.models.cash_flow_entry import CashFlowEntry
```

Agregar al final del archivo:

```python
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
```

- [ ] **Step 4: Agregar la ruta DELETE a `app/routers/plan_movements.py`**

Al final del archivo:

```python
@router.delete(
    "/plans/{plan_id}/movements/{movement_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_movement(
    plan_id: uuid.UUID,
    movement_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    plan_movement_service.delete_movement(db, user, plan_id, movement_id)
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `pytest tests/test_plan_movements.py -k "delete" -v` (Expected: PASAN).

- [ ] **Step 6: Regresión + commit**

Run: `pytest -q` (Expected: todos verdes).

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/plan_movement_service.py backend/app/routers/plan_movements.py backend/tests/test_plan_movements.py
git commit -m "feat(backend): DELETE /plans/{id}/movements/{movement_id}"
```

---

## Notas de cierre

- Al terminar: el usuario puede crear/listar/editar/borrar movimientos en un plan no-default; cada cambio materializa/recalcula su línea de tiempo. Cierra el flujo de simulación de planes.
- **Cierre:** squash-merge de `feat/plan-movements-endpoints` → un commit `feat: endpoints de plan_movements (CRUD)` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** 4 error codes (§2) — Task 1 Step 2 ✓; schemas (§2) — Task 1 Step 3 ✓; validación kind↔columnas con helper compartido (§3) — `_check_foreign_fields` + `_validate_installments`, usado en create (Task 1) y update (Task 2) ✓; POST con orden de validaciones + income_duration_months=1 + rates_add_vat default + motor (§4) — Task 1 Step 4 ✓; GET orden start_date + default `[]` (§5) — Task 1 Step 4 ✓; PATCH kind ignorado + estado final + motor (§6) — Task 2 Step 3 ✓; DELETE orquestado sin motor (§7) — Task 3 Step 3 ✓; user_id vía plan (§8) — `_get_owned_plan` ✓.
- **Placeholders:** ninguno; código completo en cada step.
- **Consistencia de tipos:** `create_movement/list_movements/update_movement/delete_movement(db, user, plan_id, ...)`, `PlanMovementOut.from_model`, helpers `_get_owned_plan`/`_get_movement`/`_validate_currency`/`_check_foreign_fields`/`_validate_installments` consistentes entre tasks; `materialize_plan_movement(db, movement.id)` igual que el motor; tests usan `seed_uy_currency`, `_plan` (POST /plans), `uuid.UUID(...)` sobre ids string. Plata como string ("45000.00").
```
