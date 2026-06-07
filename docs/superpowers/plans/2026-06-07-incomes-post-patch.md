# `POST` + `PATCH /incomes` (slice 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar `POST /incomes` (201) y `PATCH /incomes/{id}` (200) con toda la validación del modelo binario y los error codes propios, sin materialización (diferida al CashFlowEngine).

**Architecture:** Router finito → `income_service` (valida con helpers compartidos, lanza `AppError`, no conoce HTTP) → modelo `Income`. Schemas Pydantic permisivos (tipos); la validación de negocio vive en el servicio. Respuesta vía `IncomeOut.from_model` (deriva `is_deleted`).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, pytest. Python 3.13 (`backend/.venv`).

**Spec:** `docs/superpowers/specs/2026-06-07-incomes-post-patch-design.md`.

**Git:** rama `feat/incomes-post-patch`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/
├── core/errors.py            # + 10 error codes   (MODIFICAR)
├── schemas/income.py         # IncomeCreate / IncomeUpdate / IncomeOut   (NUEVO)
├── services/income_service.py # create_income / update_income + helpers   (NUEVO)
├── routers/incomes.py        # POST y PATCH   (NUEVO)
└── main.py                   # montar incomes.router   (MODIFICAR)
backend/tests/
└── test_incomes.py           # POST + PATCH   (NUEVO)
```

---

## Task 1: Error codes nuevos

**Files:** Modify `backend/app/core/errors.py`

- [ ] **Step 1: Agregar los 10 codes al enum `ErrorCode`**

En `backend/app/core/errors.py`, dentro de `class ErrorCode(Enum)`, después de la línea `validation_failed = (422, "Hay errores en el formulario.")`, agregar:

```python
    not_found = (404, "No encontrado.")
    income_type_invalid = (422, "Tipo de ingreso no válido.")
    currency_not_available = (422, "Esa moneda no está disponible. Elegí otra.")
    description_invalid = (422, "La descripción es obligatoria y debe tener al menos 8 caracteres.")
    amount_invalid = (422, "El monto debe ser mayor a 0.")
    payment_day_invalid = (422, "El día de cobro debe estar entre 1 y 31.")
    recurring_income_requires_payment_day = (422, "Un ingreso recurrente necesita un día de cobro.")
    fixed_term_income_requires_dates = (422, "Un ingreso de duración fija necesita fecha de primer cobro y cantidad de meses.")
    total_months_invalid = (422, "La cantidad de meses debe ser 1 o más.")
    income_form_inconsistent = (422, "Las columnas no corresponden a la forma del ingreso (recurrente o duración fija).")
```

- [ ] **Step 2: Verificar que importa**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && python -c "from app.core.errors import ErrorCode; print(ErrorCode.income_form_inconsistent.status_code, ErrorCode.not_found.status_code)"`
Expected: `422 404`

- [ ] **Step 3: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/core/errors.py
git commit -m "feat(backend): error codes de incomes (validación POST/PATCH)"
```

---

## Task 2: Schemas `IncomeCreate` / `IncomeUpdate` / `IncomeOut`

**Files:** Create `backend/app/schemas/income.py`

- [ ] **Step 1: Crear `backend/app/schemas/income.py`**

```python
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.income import Income


class IncomeCreate(BaseModel):
    income_type_id: int
    currency_id: int
    amount: Decimal
    description: str
    is_monthly_recurring: bool
    payment_day: int | None = None
    first_income_date: date | None = None
    total_months: int | None = None
    shift_weekends: bool | None = None


class IncomeUpdate(BaseModel):
    income_type_id: int | None = None
    currency_id: int | None = None
    amount: Decimal | None = None
    description: str | None = None
    is_monthly_recurring: bool | None = None
    payment_day: int | None = None
    first_income_date: date | None = None
    total_months: int | None = None
    shift_weekends: bool | None = None


class IncomeOut(BaseModel):
    id: uuid.UUID
    income_type_id: int
    currency_id: int
    amount: Decimal
    description: str
    is_monthly_recurring: bool
    payment_day: int | None
    first_income_date: date | None
    total_months: int | None
    shift_weekends: bool
    is_deleted: bool

    @classmethod
    def from_model(cls, income: Income) -> "IncomeOut":
        return cls(
            id=income.id,
            income_type_id=income.income_type_id,
            currency_id=income.currency_id,
            amount=income.amount,
            description=income.description,
            is_monthly_recurring=income.is_monthly_recurring,
            payment_day=income.payment_day,
            first_income_date=income.first_income_date,
            total_months=income.total_months,
            shift_weekends=income.shift_weekends,
            is_deleted=income.deleted_at is not None,
        )
```

- [ ] **Step 2: Verificar que importa**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && python -c "from app.schemas.income import IncomeCreate, IncomeUpdate, IncomeOut; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/schemas/income.py
git commit -m "feat(backend): schemas de incomes (Create/Update/Out)"
```

---

## Task 3: `POST /incomes` — servicio + router + tests (TDD)

**Files:**
- Create: `backend/app/services/income_service.py`, `backend/app/routers/incomes.py`, `backend/tests/test_incomes.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Escribir los tests de POST que fallan `backend/tests/test_incomes.py`**

```python
from decimal import Decimal

from sqlalchemy import select

from app.models.country import Country
from app.models.currency import Currency
from app.models.income import Income
from app.models.income_type import IncomeType


def _seed_refs(db_session):
    """income_types (visible + oculto) y currencies (UY válida + AR de otro país). Requiere seed_uy."""
    db_session.add(Country(code="AR", name="Argentina", visible=True, vat_rate=Decimal("21.00")))
    db_session.add_all([
        Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True),
        Currency(id=2, country_code="AR", name="Peso AR", is_legal_tender=True, allowed_in_credit_card=False),
        IncomeType(id=1, code="sueldo", name="Sueldo", visible=True),
        IncomeType(id=9, code="oculto", name="Oculto", visible=False),
    ])
    db_session.flush()


def _auth(client):
    token = client.post("/auth/register", json={"email": "u@b.com", "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _recurring_body(**over):
    body = {
        "income_type_id": 1,
        "currency_id": 1,
        "amount": "45000.00",
        "description": "Sueldo principal",
        "is_monthly_recurring": True,
        "payment_day": 5,
    }
    body.update(over)
    return body


def _fixed_body(**over):
    body = {
        "income_type_id": 1,
        "currency_id": 1,
        "amount": "30000.00",
        "description": "Freelance ocasional",
        "is_monthly_recurring": False,
        "first_income_date": "2026-07-10",
        "total_months": 1,
    }
    body.update(over)
    return body


def test_create_recurring(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(), headers=_auth(client))
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"]
    assert body["is_deleted"] is False
    assert body["payment_day"] == 5
    assert body["first_income_date"] is None
    assert body["total_months"] is None
    assert body["amount"] == "45000.00"
    assert body["shift_weekends"] is False


def test_create_fixed_term(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_fixed_body(), headers=_auth(client))
    assert resp.status_code == 201
    body = resp.json()
    assert body["first_income_date"] == "2026-07-10"
    assert body["total_months"] == 1
    assert body["payment_day"] is None


def test_create_requires_auth(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body())
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_create_ignores_body_user_id(client, db_session, seed_uy):
    _seed_refs(db_session)
    fake = "00000000-0000-0000-0000-000000000000"
    resp = client.post("/incomes", json=_recurring_body(user_id=fake), headers=_auth(client))
    assert resp.status_code == 201
    income = db_session.execute(select(Income)).scalars().one()
    assert str(income.user_id) != fake


def test_create_income_type_invalid_hidden(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(income_type_id=9), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "income_type_invalid"


def test_create_income_type_invalid_missing(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(income_type_id=123), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "income_type_invalid"


def test_create_currency_not_available(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(currency_id=2), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "currency_not_available"


def test_create_description_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(description="corta"), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "description_invalid"


def test_create_amount_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(amount="0"), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "amount_invalid"


def test_create_payment_day_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(payment_day=32), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "payment_day_invalid"


def test_create_recurring_requires_payment_day(client, db_session, seed_uy):
    _seed_refs(db_session)
    body = _recurring_body()
    del body["payment_day"]
    resp = client.post("/incomes", json=body, headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "recurring_income_requires_payment_day"


def test_create_fixed_requires_dates(client, db_session, seed_uy):
    _seed_refs(db_session)
    body = _fixed_body()
    del body["first_income_date"]
    del body["total_months"]
    resp = client.post("/incomes", json=body, headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "fixed_term_income_requires_dates"


def test_create_total_months_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_fixed_body(total_months=0), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "total_months_invalid"


def test_create_form_inconsistent_recurring_with_dates(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(first_income_date="2026-07-10"), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "income_form_inconsistent"


def test_create_form_inconsistent_fixed_with_payment_day(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_fixed_body(payment_day=5), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "income_form_inconsistent"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_incomes.py -q`
Expected: FALLAN (no existe el endpoint `/incomes` → 404, o ImportError del servicio).

- [ ] **Step 3: Crear el servicio `backend/app/services/income_service.py`**

```python
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.currency import Currency
from app.models.income import Income
from app.models.income_type import IncomeType
from app.models.user import User
from app.schemas.income import IncomeCreate, IncomeUpdate

MIN_DESCRIPTION_LENGTH = 8


def _validate_income_type(db: Session, income_type_id: int | None) -> None:
    income_type = db.get(IncomeType, income_type_id) if income_type_id is not None else None
    if income_type is None or not income_type.visible:
        raise AppError(ErrorCode.income_type_invalid, field="income_type_id")


def _validate_currency(db: Session, user: User, currency_id: int | None) -> None:
    currency = db.get(Currency, currency_id) if currency_id is not None else None
    if currency is None or currency.country_code != user.country_code:
        raise AppError(ErrorCode.currency_not_available, field="currency_id")


def _validate_amount(amount: Decimal | None) -> None:
    if amount is None or amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")


def _validate_description(description: str | None) -> str:
    cleaned = (description or "").strip()
    if len(cleaned) < MIN_DESCRIPTION_LENGTH:
        raise AppError(ErrorCode.description_invalid, field="description")
    return cleaned


def _validate_payment_day(payment_day: int | None) -> None:
    if payment_day is not None and not (1 <= payment_day <= 31):
        raise AppError(ErrorCode.payment_day_invalid, field="payment_day")


def _validate_form(
    is_monthly_recurring: bool,
    payment_day: int | None,
    first_income_date,
    total_months: int | None,
) -> None:
    """Modelo binario: recurrente infinito o duración fija. Valida el estado final."""
    if is_monthly_recurring:
        if payment_day is None:
            raise AppError(ErrorCode.recurring_income_requires_payment_day, field="payment_day")
        if first_income_date is not None or total_months is not None:
            raise AppError(ErrorCode.income_form_inconsistent)
    else:
        if first_income_date is None or total_months is None:
            raise AppError(ErrorCode.fixed_term_income_requires_dates)
        if total_months < 1:
            raise AppError(ErrorCode.total_months_invalid, field="total_months")
        if payment_day is not None:
            raise AppError(ErrorCode.income_form_inconsistent)


def create_income(db: Session, user: User, payload: IncomeCreate) -> Income:
    _validate_income_type(db, payload.income_type_id)
    _validate_currency(db, user, payload.currency_id)
    _validate_amount(payload.amount)
    description = _validate_description(payload.description)
    _validate_payment_day(payload.payment_day)
    _validate_form(
        payload.is_monthly_recurring, payload.payment_day, payload.first_income_date, payload.total_months
    )

    income = Income(
        user_id=user.id,
        income_type_id=payload.income_type_id,
        currency_id=payload.currency_id,
        amount=payload.amount,
        description=description,
        is_monthly_recurring=payload.is_monthly_recurring,
        payment_day=payload.payment_day,
        first_income_date=payload.first_income_date,
        total_months=payload.total_months,
        shift_weekends=payload.shift_weekends or False,
    )
    db.add(income)
    db.commit()
    db.refresh(income)
    return income


def update_income(db: Session, user: User, income_id: uuid.UUID, payload: IncomeUpdate) -> Income:
    from sqlalchemy import select

    income = db.execute(
        select(Income).where(
            Income.id == income_id,
            Income.user_id == user.id,
            Income.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if income is None:
        raise AppError(ErrorCode.not_found)

    fields = payload.model_fields_set

    # Campos no-nullable que no aceptan null explícito en PATCH
    for f in ("is_monthly_recurring", "shift_weekends"):
        if f in fields and getattr(payload, f) is None:
            raise AppError(ErrorCode.validation_failed, field=f)

    # Validación por campo presente
    if "income_type_id" in fields:
        _validate_income_type(db, payload.income_type_id)
    if "currency_id" in fields:
        _validate_currency(db, user, payload.currency_id)
    if "amount" in fields:
        _validate_amount(payload.amount)
    new_description = None
    if "description" in fields:
        new_description = _validate_description(payload.description)
    if "payment_day" in fields:
        _validate_payment_day(payload.payment_day)

    # Estado final (merge) y validación de forma
    final_recurring = payload.is_monthly_recurring if "is_monthly_recurring" in fields else income.is_monthly_recurring
    final_payment_day = payload.payment_day if "payment_day" in fields else income.payment_day
    final_first = payload.first_income_date if "first_income_date" in fields else income.first_income_date
    final_total = payload.total_months if "total_months" in fields else income.total_months
    _validate_form(final_recurring, final_payment_day, final_first, final_total)

    # Aplicar solo los campos presentes
    if "income_type_id" in fields:
        income.income_type_id = payload.income_type_id
    if "currency_id" in fields:
        income.currency_id = payload.currency_id
    if "amount" in fields:
        income.amount = payload.amount
    if "description" in fields:
        income.description = new_description
    if "is_monthly_recurring" in fields:
        income.is_monthly_recurring = payload.is_monthly_recurring
    if "payment_day" in fields:
        income.payment_day = payload.payment_day
    if "first_income_date" in fields:
        income.first_income_date = payload.first_income_date
    if "total_months" in fields:
        income.total_months = payload.total_months
    if "shift_weekends" in fields:
        income.shift_weekends = payload.shift_weekends

    db.commit()
    db.refresh(income)
    return income
```

- [ ] **Step 4: Crear el router `backend/app/routers/incomes.py` (solo POST por ahora)**

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.income import IncomeCreate, IncomeOut
from app.services import income_service

router = APIRouter(tags=["incomes"])


@router.post("/incomes", response_model=IncomeOut, status_code=status.HTTP_201_CREATED)
def create_income(
    payload: IncomeCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeOut:
    income = income_service.create_income(db, user, payload)
    return IncomeOut.from_model(income)
```

- [ ] **Step 5: Montar el router en `backend/app/main.py`**

Agregar `incomes` al import de routers (orden alfabético) y montarlo. El import queda:

```python
from app.routers import auth, bootstrap, countries, health, incomes
```

Y agregar al final, después de `app.include_router(bootstrap.router)`:

```python
app.include_router(incomes.router)
```

- [ ] **Step 6: Correr y verificar que pasan los tests de POST**

Run: `pytest tests/test_incomes.py -q`
Expected: PASAN todos los tests de POST.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/income_service.py backend/app/routers/incomes.py backend/app/main.py backend/tests/test_incomes.py
git commit -m "feat(backend): POST /incomes con validación del modelo binario"
```

---

## Task 4: `PATCH /incomes/{id}` — router + tests (TDD)

> El servicio `update_income` ya quedó escrito en la Task 3. Acá se agrega el endpoint y sus tests.

**Files:**
- Modify: `backend/app/routers/incomes.py`, `backend/tests/test_incomes.py`

- [ ] **Step 1: Agregar los tests de PATCH a `backend/tests/test_incomes.py`**

Agregar al final del archivo (reusan los helpers `_seed_refs`, `_auth`, `_recurring_body`, `_fixed_body` ya definidos):

```python
def _create_recurring(client, headers, **over):
    return client.post("/incomes", json=_recurring_body(**over), headers=headers).json()


def test_patch_payment_day(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(f"/incomes/{income['id']}", json={"payment_day": 15}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["payment_day"] == 15


def test_patch_absent_field_untouched(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(f"/incomes/{income['id']}", json={"payment_day": 10}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["description"] == "Sueldo principal"  # no se tocó


def test_patch_convert_recurring_to_fixed(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(
        f"/incomes/{income['id']}",
        json={
            "is_monthly_recurring": False,
            "first_income_date": "2026-12-15",
            "total_months": 6,
            "payment_day": None,  # null explícito borra el día
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_monthly_recurring"] is False
    assert body["payment_day"] is None
    assert body["first_income_date"] == "2026-12-15"
    assert body["total_months"] == 6


def test_patch_inconsistent_final_state(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    # recurrente + first_income_date suelto => estado final inválido
    resp = client.patch(f"/incomes/{income['id']}", json={"first_income_date": "2026-12-15"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "income_form_inconsistent"


def test_patch_not_found(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    resp = client.patch(
        "/incomes/00000000-0000-0000-0000-000000000000", json={"payment_day": 10}, headers=headers
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_patch_requires_auth(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.patch("/incomes/00000000-0000-0000-0000-000000000000", json={"payment_day": 10})
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_patch_amount_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(f"/incomes/{income['id']}", json={"amount": "0"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "amount_invalid"
```

- [ ] **Step 2: Correr y verificar que fallan los nuevos**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_incomes.py -q`
Expected: FALLAN los tests de PATCH (el endpoint PATCH no existe → 404/405).

- [ ] **Step 3: Agregar el endpoint PATCH al router `backend/app/routers/incomes.py`**

Cambiar el import de schemas para incluir `IncomeUpdate`:

```python
from app.schemas.income import IncomeCreate, IncomeOut, IncomeUpdate
```

Y agregar `import uuid` arriba de todo, y al final del archivo el endpoint:

```python
@router.patch("/incomes/{income_id}", response_model=IncomeOut)
def update_income(
    income_id: uuid.UUID,
    payload: IncomeUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeOut:
    income = income_service.update_income(db, user, income_id, payload)
    return IncomeOut.from_model(income)
```

- [ ] **Step 4: Correr y verificar que pasa toda la suite de incomes**

Run: `pytest tests/test_incomes.py -q`
Expected: PASAN todos (POST + PATCH).

- [ ] **Step 5: Regresión de la suite completa**

Run: `pytest -q`
Expected: pasan todos (los previos + los nuevos de incomes).

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/routers/incomes.py backend/tests/test_incomes.py
git commit -m "feat(backend): PATCH /incomes/{id} con validación de consistencia post-merge"
```

---

## Notas de cierre

- Al terminar: `POST /incomes` (201) y `PATCH /incomes/{id}` (200) andando, con validación completa del modelo binario y los error codes. Sin materialización (slice diferido). Sin `GET`/`DELETE` (slice 3).
- **Cierre:** squash-merge de `feat/incomes-post-patch` → un commit `feat: POST + PATCH incomes` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** validación en servicio con codes propios (§2) — Task 3 servicio ✓; contrato POST/PATCH y los 10 codes (§3, §8) — Task 1 + Task 3/4 ✓; modelo binario y validación del estado final en PATCH (§4) — `_validate_form` + merge en `update_income` ✓; schemas Create/Update/Out + `model_fields_set` + `is_deleted` derivado (§5) — Task 2 + `update_income` ✓; helpers compartidos (§6) — Task 3 servicio ✓; router + mount (§7) — Task 3/4 ✓; testing (§9) — Task 3/4 tests ✓.
- **Placeholders:** ninguno; código completo en cada paso.
- **Consistencia de tipos:** `IncomeCreate`/`IncomeUpdate`/`IncomeOut` (Task 2) usados igual en servicio (Task 3) y router (Task 3/4); `create_income(db, user, payload)` y `update_income(db, user, income_id, payload)` con las mismas firmas en servicio, router y plan; `IncomeOut.from_model(income)` consistente en POST y PATCH; los helpers `_validate_*` se usan en `create_income` y `update_income`; `model_fields_set` es la API real de Pydantic v2.
- **Nota de diseño:** `amount` se serializa como string en JSON (convención del proyecto: Pydantic serializa `Decimal` como string), por eso los tests comparan `body["amount"] == "45000.00"`.
```
