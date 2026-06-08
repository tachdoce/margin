# Endpoints de expenses (6a) — Plan de implementación

> **For agentic workers:** Ejecutar según el modo que elija el usuario (inline o subagente con higiene de
> comandos: `cd` no `git -C`, sin `2>&1`). TDD: test → rojo → implementación → verde → commit por task.

**Goal:** Los 3 endpoints de gastos (`POST/PATCH/GET expenses`), cableando validación por kind →
`ReviewEngine.review_obligation` → `CashFlowEngine.materialize_expense` en una transacción.

**Architecture:** Router finito → `expense_service` (validaciones + orquestación) → modelo `Obligation`.
Reusa `scoping.require_user_currency`, `review_obligation` (#5, con un amend), `materialize_expense` (#2).
Schemas en `app/schemas/expense.py`. Error codes nuevos en `errors.py`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, pytest. Spec:
`docs/superpowers/specs/2026-06-08-endpoints-expenses-design.md`.

**Rama:** `feat/endpoints-expenses` → squash-merge a `main`.

---

## Task 0: Crear la rama

- [ ] **Step 1:**

```bash
git checkout -b feat/endpoints-expenses
```

---

## Task 1: Amend al reviewer (short-circuit `is_closed`)

**Files:**
- Modify: `backend/app/services/review/obligations.py`
- Test: `backend/tests/test_review_obligations.py` (agregar 1 test)

- [ ] **Step 1: Agregar el test (rojo)**

En `backend/tests/test_review_obligations.py`, agregar:

```python
def test_is_closed_short_circuit(db_session, user):
    # tasas que normalmente dispararían findings, pero cerrada → short-circuit
    o = _deuda(db_session, user, financing_rate=Decimal("200.00"), overdue_rate=Decimal("10.00"),
               is_closed=True)
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.review_findings == "[]"
    assert o.is_ready is True
```

- [ ] **Step 2: Correr, verificar que falla**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_review_obligations.py::test_is_closed_short_circuit -q
```
Esperado: FAIL (review_findings tendría los 2 codes, is_ready False).

- [ ] **Step 3: Implementar el short-circuit**

En `backend/app/services/review/obligations.py`, dentro de `review_obligation`, **después** del
`if obligation is None: return` y **antes** de `findings = _findings(obligation)`, insertar:

```python
    if obligation.is_closed:
        # una obligación cerrada está resuelta: sin findings, lista. No se corren las reglas.
        obligation.reviewed_at = datetime.now(timezone.utc)
        obligation.review_findings = "[]"
        obligation.is_ready = True
        db.flush()
        return
```

- [ ] **Step 4: Correr, verificar verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_review_obligations.py -q
```
Esperado: PASS (10 tests: 9 previos + 1 nuevo).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/review/obligations.py backend/tests/test_review_obligations.py
git commit -m "feat: review_obligation hace short-circuit si is_closed

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Error codes + schemas + POST + GET + router

**Files:**
- Modify: `backend/app/core/errors.py`
- Create: `backend/app/schemas/expense.py`
- Create: `backend/app/services/expense_service.py`
- Create: `backend/app/routers/expenses.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_expenses.py`

- [ ] **Step 1: Agregar error codes**

En `backend/app/core/errors.py`, dentro del enum `ErrorCode` (tras `movement_fields_invalid`):

```python
    expense_type_invalid = (422, "Tipo de gasto no válido.")
    priority_level_invalid = (422, "Nivel de prioridad no válido.")
    due_day_invalid = (422, "El día de vencimiento debe estar entre 1 y 31.")
    one_time_expense_inconsistent = (422, "Un gasto con fecha única debe ser no recurrente y sin día de vencimiento.")
    expense_recurring_requires_due_day = (422, "Un gasto recurrente necesita un día de vencimiento.")
    one_time_date_in_past = (422, "La fecha del gasto no puede ser anterior a hoy.")
```
(`description_invalid`, `amount_invalid`, `currency_not_available`, `not_found`, `field_not_nullable` ya
existen.)

- [ ] **Step 2: Escribir los tests de POST y GET (rojo)**

`backend/tests/test_expenses.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel

FUTURE = (date.today() + timedelta(days=40)).isoformat()
PAST = (date.today() - timedelta(days=2)).isoformat()


@pytest.fixture
def catalog(db_session, seed_uy_currency):
    db_session.add_all([
        PriorityLevel(level=1, name="Ineludible", description="x"),
        PriorityLevel(level=2, name="Esencial", description="x"),
        PriorityLevel(level=3, name="Crítica", description="x"),
    ])
    db_session.flush()
    db_session.add_all([
        ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                       description="x", default_priority_level=2, visible=True),
        ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                       description="x", default_priority_level=3, visible=True),
    ])
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _recurrente(**over):
    body = {
        "obligation_type_id": 1, "priority_level": 2, "description": "Alquiler depto",
        "is_monthly_recurring": True, "due_day": 10, "currency_id": 1, "amount": "32000.00",
    }
    body.update(over)
    return body


def _unico(**over):
    body = {
        "obligation_type_id": 1, "priority_level": 3, "description": "Matrícula curso",
        "is_monthly_recurring": False, "first_due_date": FUTURE, "currency_id": 1, "amount": "12000.00",
    }
    body.update(over)
    return body


def _entries(db_session, obligation_id):
    return list(db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_type == "gasto",
                                    CashFlowEntry.source_id == obligation_id)
    ).scalars())


# --- POST ---

def test_post_recurrente_materializa(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_monthly_recurring"] is True
    assert body["amount"] == "32000.00"
    assert body["review_findings"] == []
    assert body["is_ready"] is True
    assert len(_entries(db_session, body["id"])) > 0  # materializó


def test_post_unico_una_entry(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_unico(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["due_day"] is None
    assert len(_entries(db_session, body["id"])) == 1


def test_post_kind_deuda_rechazado(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(obligation_type_id=10), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "expense_type_invalid"


def test_post_priority_sistema_rechazado(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(priority_level=1), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "priority_level_invalid"


def test_post_description_corta(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(description="corta"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "description_invalid"


def test_post_amount_invalido(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(amount="0"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "amount_invalid"


def test_post_due_day_fuera_de_rango(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(due_day=40), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "due_day_invalid"


def test_post_recurrente_sin_due_day(client, db_session, catalog):
    headers = _auth(client)
    body = _recurrente()
    del body["due_day"]
    resp = client.post("/expenses", json=body, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "expense_recurring_requires_due_day"


def test_post_recurrente_con_first_due_date(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(first_due_date=FUTURE), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "one_time_expense_inconsistent"


def test_post_unico_sin_first_due_date(client, db_session, catalog):
    headers = _auth(client)
    body = _unico()
    del body["first_due_date"]
    resp = client.post("/expenses", json=body, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "one_time_expense_inconsistent"


def test_post_unico_fecha_pasada(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/expenses", json=_unico(first_due_date=PAST), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "one_time_date_in_past"


def test_post_moneda_otro_pais(client, db_session, catalog):
    from app.models.country import Country
    from app.models.currency import Currency
    db_session.add(Country(code="AR", name="Argentina", visible=True, vat_rate=Decimal("21.00")))
    db_session.flush()
    db_session.add(Currency(id=2, country_code="AR", name="Peso AR", is_legal_tender=True,
                            allowed_in_credit_card=False))
    db_session.flush()
    headers = _auth(client)
    resp = client.post("/expenses", json=_recurrente(currency_id=2), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "currency_not_available"


def test_post_sin_token(client, db_session, catalog):
    resp = client.post("/expenses", json=_recurrente())
    assert resp.status_code == 401


# --- GET ---

def test_get_lista_solo_gastos(client, db_session, catalog):
    headers = _auth(client)
    client.post("/expenses", json=_recurrente(description="Alquiler uno"), headers=headers)
    client.post("/expenses", json=_unico(description="Matrícula dos"), headers=headers)
    resp = client.get("/expenses", headers=headers)
    assert resp.status_code == 200
    expenses = resp.json()["expenses"]
    assert len(expenses) == 2


def test_get_vacio(client, db_session, catalog):
    headers = _auth(client)
    resp = client.get("/expenses", headers=headers)
    assert resp.json() == {"expenses": []}


def test_get_sin_token(client, db_session, catalog):
    assert client.get("/expenses").status_code == 401
```

- [ ] **Step 3: Correr, verificar que fallan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_expenses.py -q
```
Esperado: FAIL (no existe el endpoint / módulos).

- [ ] **Step 4: Crear el schema**

`backend/app/schemas/expense.py`:

```python
import json
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.obligation import Obligation


class ExpenseCreate(BaseModel):
    obligation_type_id: int
    priority_level: int
    description: str
    is_monthly_recurring: bool
    due_day: int | None = None
    first_due_date: date | None = None
    currency_id: int
    amount: Decimal
    shift_weekends: bool | None = None


class ExpenseUpdate(BaseModel):
    obligation_type_id: int | None = None
    priority_level: int | None = None
    description: str | None = None
    is_monthly_recurring: bool | None = None
    due_day: int | None = None
    first_due_date: date | None = None
    currency_id: int | None = None
    amount: Decimal | None = None
    shift_weekends: bool | None = None
    is_closed: bool | None = None


class ExpenseOut(BaseModel):
    id: uuid.UUID
    obligation_type_id: int
    priority_level: int
    description: str | None
    is_monthly_recurring: bool
    due_day: int | None
    first_due_date: date | None
    currency_id: int
    amount: Decimal
    shift_weekends: bool
    is_closed: bool
    review_findings: list[str]
    is_ready: bool

    @classmethod
    def from_model(cls, o: Obligation) -> "ExpenseOut":
        return cls(
            id=o.id,
            obligation_type_id=o.obligation_type_id,
            priority_level=o.priority_level,
            description=o.description,
            is_monthly_recurring=o.is_monthly_recurring,
            due_day=o.due_day,
            first_due_date=o.first_due_date,
            currency_id=o.currency_id,
            amount=o.amount,
            shift_weekends=o.shift_weekends,
            is_closed=o.is_closed,
            review_findings=json.loads(o.review_findings),
            is_ready=o.is_ready,
        )
```

- [ ] **Step 5: Crear el servicio**

`backend/app/services/expense_service.py`:

```python
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.user import User
from app.schemas.expense import ExpenseCreate, ExpenseUpdate
from app.services.cash_flow.expenses import materialize_expense
from app.services.review.obligations import review_obligation
from app.services.scoping import require_user_currency

MIN_DESCRIPTION_LENGTH = 8
SYSTEM_PRIORITY_LEVEL = 1  # Ineludible: solo lo asigna el sistema


def _require_gasto_type(db: Session, obligation_type_id: int | None) -> None:
    ot = db.get(ObligationType, obligation_type_id) if obligation_type_id is not None else None
    if ot is None or ot.obligation_kind != "gasto":
        raise AppError(ErrorCode.expense_type_invalid, field="obligation_type_id")


def _validate_priority(db: Session, priority_level: int | None) -> None:
    if (
        priority_level is None
        or priority_level == SYSTEM_PRIORITY_LEVEL
        or db.get(PriorityLevel, priority_level) is None
    ):
        raise AppError(ErrorCode.priority_level_invalid, field="priority_level")


def _validate_description(description: str | None) -> str:
    cleaned = (description or "").strip()
    if len(cleaned) < MIN_DESCRIPTION_LENGTH:
        raise AppError(ErrorCode.description_invalid, field="description")
    return cleaned


def _validate_amount(amount) -> None:
    if amount is None or amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")


def _validate_due_day(due_day: int | None) -> None:
    if due_day is not None and not (1 <= due_day <= 31):
        raise AppError(ErrorCode.due_day_invalid, field="due_day")


def _validate_form(is_monthly_recurring: bool, due_day, first_due_date) -> None:
    if is_monthly_recurring:
        if due_day is None:
            raise AppError(ErrorCode.expense_recurring_requires_due_day, field="due_day")
        if first_due_date is not None:
            raise AppError(ErrorCode.one_time_expense_inconsistent, field="first_due_date")
    else:
        if first_due_date is None or due_day is not None:
            raise AppError(ErrorCode.one_time_expense_inconsistent, field="first_due_date")


def _validate_first_due_date_future(first_due_date) -> None:
    if first_due_date is not None and first_due_date < date.today():
        raise AppError(ErrorCode.one_time_date_in_past, field="first_due_date")


def _gasto_query(user: User):
    return (
        select(Obligation)
        .join(ObligationType, ObligationType.id == Obligation.obligation_type_id)
        .where(Obligation.user_id == user.id, ObligationType.obligation_kind == "gasto")
    )


def create_expense(db: Session, user: User, payload: ExpenseCreate) -> Obligation:
    _require_gasto_type(db, payload.obligation_type_id)
    require_user_currency(db, user, payload.currency_id)
    _validate_priority(db, payload.priority_level)
    description = _validate_description(payload.description)
    _validate_amount(payload.amount)
    _validate_due_day(payload.due_day)
    _validate_form(payload.is_monthly_recurring, payload.due_day, payload.first_due_date)
    _validate_first_due_date_future(payload.first_due_date)

    obligation = Obligation(
        user_id=user.id,
        obligation_type_id=payload.obligation_type_id,
        priority_level=payload.priority_level,
        description=description,
        is_monthly_recurring=payload.is_monthly_recurring,
        due_day=payload.due_day,
        first_due_date=payload.first_due_date,
        currency_id=payload.currency_id,
        amount=payload.amount,
        shift_weekends=payload.shift_weekends if payload.shift_weekends is not None else False,
        total_installments=None,
        financing_rate=None,
        overdue_rate=None,
        rates_add_vat=True,
        origin_obligation_id=None,
        institution_id=None,
        is_closed=False,
        reviewed_at=None,
        review_findings="[]",
        user_acknowledged_at=None,
        is_ready=False,
    )
    db.add(obligation)
    db.flush()
    review_obligation(db, obligation.id)
    materialize_expense(db, obligation.id)
    db.commit()
    db.refresh(obligation)
    return obligation


def list_expenses(db: Session, user: User) -> list[Obligation]:
    return list(
        db.execute(_gasto_query(user).order_by(Obligation.created_at.desc())).scalars()
    )


def update_expense(db: Session, user: User, obligation_id: uuid.UUID, payload: ExpenseUpdate) -> Obligation:
    obligation = db.execute(
        _gasto_query(user).where(Obligation.id == obligation_id)
    ).scalar_one_or_none()
    if obligation is None:
        raise AppError(ErrorCode.not_found)

    fields = payload.model_fields_set

    if "obligation_type_id" in fields:
        _require_gasto_type(db, payload.obligation_type_id)
    if "currency_id" in fields:
        require_user_currency(db, user, payload.currency_id)
    if "priority_level" in fields:
        _validate_priority(db, payload.priority_level)
    if "description" in fields:
        _validate_description(payload.description)
    if "amount" in fields:
        _validate_amount(payload.amount)
    if "due_day" in fields:
        _validate_due_day(payload.due_day)
    for f in ("is_monthly_recurring", "shift_weekends", "is_closed"):
        if f in fields and getattr(payload, f) is None:
            raise AppError(ErrorCode.field_not_nullable, field=f)

    old_first_due_date = obligation.first_due_date
    for f in fields:
        value = getattr(payload, f)
        if f == "description":
            value = value.strip()
        setattr(obligation, f, value)

    _validate_form(obligation.is_monthly_recurring, obligation.due_day, obligation.first_due_date)
    if (
        "first_due_date" in fields
        and obligation.first_due_date is not None
        and obligation.first_due_date != old_first_due_date
    ):
        _validate_first_due_date_future(obligation.first_due_date)

    db.flush()
    review_obligation(db, obligation.id)
    materialize_expense(db, obligation.id)
    db.commit()
    db.refresh(obligation)
    return obligation
```

- [ ] **Step 6: Crear el router**

`backend/app/routers/expenses.py`:

```python
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.expense import ExpenseCreate, ExpenseOut, ExpenseUpdate
from app.services import expense_service

router = APIRouter(tags=["expenses"])


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExpenseOut:
    return ExpenseOut.from_model(expense_service.create_expense(db, user, payload))


@router.get("/expenses")
def list_expenses(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"expenses": [ExpenseOut.from_model(o) for o in expense_service.list_expenses(db, user)]}


@router.patch("/expenses/{obligation_id}", response_model=ExpenseOut)
def update_expense(
    obligation_id: uuid.UUID,
    payload: ExpenseUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExpenseOut:
    return ExpenseOut.from_model(expense_service.update_expense(db, user, obligation_id, payload))
```

- [ ] **Step 7: Registrar el router en `main.py`**

En `backend/app/main.py`: agregar `expenses` al import de routers y `app.include_router(expenses.router)`:
```python
from app.routers import auth, bootstrap, countries, expenses, health, incomes, plan_movements, plans
...
app.include_router(expenses.router)
```

- [ ] **Step 8: Correr los tests de POST/GET, verificar verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_expenses.py -q
```
Esperado: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/core/errors.py backend/app/schemas/expense.py backend/app/services/expense_service.py backend/app/routers/expenses.py backend/app/main.py backend/tests/test_expenses.py
git commit -m "feat: endpoints POST/GET expenses

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: PATCH expenses

**Files:**
- Test: `backend/tests/test_expenses.py` (agregar tests de PATCH)

(El servicio `update_expense` y el router ya quedaron escritos en Task 2; esta task agrega sus tests.)

- [ ] **Step 1: Agregar los tests de PATCH**

En `backend/tests/test_expenses.py`, agregar:

```python
def _create_recurrente(client, headers):
    return client.post("/expenses", json=_recurrente(), headers=headers).json()


def test_patch_cambia_amount(client, db_session, catalog):
    headers = _auth(client)
    exp = _create_recurrente(client, headers)
    resp = client.patch(f"/expenses/{exp['id']}", json={"amount": "35000.00"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["amount"] == "35000.00"
    assert any(e.amount == Decimal("35000.00") for e in _entries(db_session, exp["id"]))


def test_patch_cerrar_limpia_futuras(client, db_session, catalog):
    headers = _auth(client)
    exp = _create_recurrente(client, headers)
    assert len(_entries(db_session, exp["id"])) > 0
    resp = client.patch(f"/expenses/{exp['id']}", json={"is_closed": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_closed"] is True
    assert resp.json()["review_findings"] == []
    assert resp.json()["is_ready"] is True
    assert _entries(db_session, exp["id"]) == []  # motor limpió las futuras


def test_patch_recurrente_a_unico(client, db_session, catalog):
    headers = _auth(client)
    exp = _create_recurrente(client, headers)
    resp = client.patch(
        f"/expenses/{exp['id']}",
        json={"is_monthly_recurring": False, "due_day": None, "first_due_date": FUTURE},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_monthly_recurring"] is False
    assert resp.json()["first_due_date"] == FUTURE
    assert len(_entries(db_session, exp["id"])) == 1


def test_patch_estado_final_inconsistente(client, db_session, catalog):
    headers = _auth(client)
    exp = _create_recurrente(client, headers)
    # quitar due_day sin pasar a único → recurrente sin due_day
    resp = client.patch(f"/expenses/{exp['id']}", json={"due_day": None}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "expense_recurring_requires_due_day"


def test_patch_otro_usuario_404(client, db_session, catalog):
    headers_a = _auth(client, email="a@b.com")
    exp = _create_recurrente(client, headers_a)
    headers_b = _auth(client, email="b@b.com")
    resp = client.patch(f"/expenses/{exp['id']}", json={"amount": "1.00"}, headers=headers_b)
    assert resp.status_code == 404


def test_patch_vacio_ok(client, db_session, catalog):
    headers = _auth(client)
    exp = _create_recurrente(client, headers)
    resp = client.patch(f"/expenses/{exp['id']}", json={}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["amount"] == "32000.00"
```

- [ ] **Step 2: Correr, verificar verde** (el servicio ya está implementado)

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_expenses.py -q
```
Esperado: PASS (POST/GET + PATCH).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_expenses.py
git commit -m "test: PATCH expenses

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Suite completa

- [ ] **Step 1:**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```
Esperado: PASS (todo verde).

---

## Cierre

Tras Task 4 verde: **finishing-a-development-branch** → squash-merge `feat/endpoints-expenses` a `main` →
push (manual/prompteado).
