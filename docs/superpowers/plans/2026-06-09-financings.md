# financings — subdominio CRUD — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** El subdominio `financings` completo: enum + tabla + modelo + migración + 4 endpoints
(POST/GET/PATCH/DELETE). Sin motor ni ciclo de revisión.

**Architecture:** Router thin → service (valida, controla commit) → modelo `Financing`. Validación de cronograma
anclada en `installment_start_date` (POST sobre el body, PATCH sobre el estado final post-merge). Validación de
`currency_id` por país vía `scoping.require_user_currency`.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · pytest.

**Spec:** `docs/superpowers/specs/2026-06-09-financings-design.md`

**Branch:** `feat/financings` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

**Patrones del repo (verificados):**
- Enum nativo: en el modelo `Enum("a","b","c", name="financing_usage")`; en la migración igual + en `downgrade`
  `sa.Enum(name='financing_usage').drop(op.get_bind(), checkfirst=True)` (ver
  `2960225ce5c0_create_plans_and_plan_movements.py`).
- `scoping.require_user_currency(db, user, currency_id)` → devuelve `Currency` o levanta 422
  `currency_not_available`.
- `description_invalid`, `amount_invalid`, `installments_invalid`, `rates_negative`, `empty_patch`,
  `not_found` YA existen. Solo `usage_preference_invalid` es nuevo.
- Pydantic v2 serializa `Decimal` como string. Tests sobre Postgres `margin_test` (`create_all` + savepoint) —
  `create_all` toma el modelo nuevo, **no** dependen de la migración. Fixtures: `seed_uy_currency` (Peso id 1).
  Helpers `_headers`/`_last_user` (ver slices previos).

---

## File Structure

| Archivo | Cambio |
|---|---|
| `app/models/financing.py` | modelo `Financing` |
| `app/models/__init__.py` | registrar `Financing` |
| `alembic/versions/<rev>_create_financings.py` | enum + tabla (autogenerate + verificación) |
| `app/core/errors.py` | + `usage_preference_invalid` |
| `app/schemas/financing.py` | `FinancingCreate`, `FinancingUpdate`, `FinancingOut` |
| `app/services/financing_service.py` | `create/list/update/delete` + helpers de validación |
| `app/routers/financings.py` | 4 rutas |
| `app/main.py` | registrar el router |
| `tests/test_financings_*.py` | model / create / read / update / delete |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/financings
```

---

## Task 1: Modelo + migración

**Files:** `app/models/financing.py`, `app/models/__init__.py`,
`alembic/versions/<rev>_create_financings.py`, `tests/test_financings_model.py`

- [ ] **Step 1: Test del modelo (rojo)** `tests/test_financings_model.py`:

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.financing import Financing
from app.models.user import User


def _user(db_session, client):
    client.post("/auth/register", json={"email": "u@b.com", "password": "12345678"})
    return db_session.execute(select(User)).scalars().all()[-1]


def test_insert_with_schedule(client, db_session, seed_uy_currency):
    user = _user(db_session, client)
    f = Financing(
        user_id=user.id, currency_id=1, description="Préstamo Itaú", principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1), installment_start_date=date(2026, 8, 1),
        installment_amount=Decimal("10500.00"), total_installments=24,
        financing_rate=Decimal("72.00"), overdue_rate=Decimal("85.00"), usage_preference="primera_opcion",
    )
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)
    assert f.rates_add_vat is True   # default
    assert f.total_installments == 24


def test_insert_without_schedule(client, db_session, seed_uy_currency):
    user = _user(db_session, client)
    f = Financing(
        user_id=user.id, currency_id=1, description="Mi viejo me presta", principal_amount=Decimal("50000.00"),
        usage_preference="si_necesario",
    )
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)
    assert f.installment_start_date is None
    assert f.financing_rate is None
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_financings_model.py -q
```

Expected: FALLA (`ModuleNotFoundError: app.models.financing`).

- [ ] **Step 3: Modelo** `app/models/financing.py`:

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Financing(Base):
    __tablename__ = "financings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    description: Mapped[str] = mapped_column(String(100), nullable=False)
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    installment_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    installment_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_installments: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    financing_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    rates_add_vat: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    usage_preference: Mapped[str] = mapped_column(
        Enum("primera_opcion", "si_necesario", "ultimo_recurso", name="financing_usage"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Registrar el modelo** en `app/models/__init__.py` siguiendo el patrón existente (agregar el
  import de `Financing` junto a los demás, p.ej. `from app.models.financing import Financing` y, si hay
  `__all__`, sumarlo).

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_financings_model.py -q
```

- [ ] **Step 6: Migración (autogenerate + verificación).** La DB de dev debe estar en head; generar:

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic revision --autogenerate -m "create financings"
```

Abrir el archivo generado en `alembic/versions/` y **verificar**:
- `upgrade()` crea la tabla `financings` con TODAS las columnas (incluido el tipo enum `financing_usage`).
- `downgrade()` hace `op.drop_table('financings')` **y** dropea el enum:
  `sa.Enum(name='financing_usage').drop(op.get_bind(), checkfirst=True)`. Si autogenerate no lo agregó,
  agregarlo a mano (patrón en `2960225ce5c0_create_plans_and_plan_movements.py`).
- Que no haya cambios espurios de otras tablas (si los hay, borrarlos del archivo).

Aplicar a la DB de dev:

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic upgrade head
```

Expected: sube sin error.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/financing.py app/models/__init__.py alembic/versions/ tests/test_financings_model.py && git commit -m "feat: tabla financings (modelo + migración)"
```

---

## Task 2: Errores + schemas + service + POST

**Files:** `app/core/errors.py`, `app/schemas/financing.py`, `app/services/financing_service.py`,
`app/routers/financings.py`, `app/main.py`, `tests/test_financings_create.py`

- [ ] **Step 1: Code** en `app/core/errors.py` (dentro de `ErrorCode`):

```python
    usage_preference_invalid = (422, "Preferencia de uso no válida.")
```

- [ ] **Step 2: Schemas** `app/schemas/financing.py`:

```python
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.financing import Financing


class FinancingCreate(BaseModel):
    currency_id: int
    description: str
    principal_amount: Decimal
    usage_preference: str
    start_date: date | None = None
    installment_start_date: date | None = None
    installment_amount: Decimal | None = None
    total_installments: int | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool = True


class FinancingUpdate(BaseModel):
    currency_id: int | None = None
    description: str | None = None
    principal_amount: Decimal | None = None
    usage_preference: str | None = None
    start_date: date | None = None
    installment_start_date: date | None = None
    installment_amount: Decimal | None = None
    total_installments: int | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool | None = None


class FinancingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    currency_id: int
    description: str
    principal_amount: Decimal
    usage_preference: str
    start_date: date | None
    installment_start_date: date | None
    installment_amount: Decimal | None
    total_installments: int | None
    financing_rate: Decimal | None
    overdue_rate: Decimal | None
    rates_add_vat: bool
```

- [ ] **Step 3: Service** `app/services/financing_service.py`:

```python
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.financing import Financing
from app.models.user import User
from app.schemas.financing import FinancingCreate, FinancingUpdate
from app.services.scoping import require_user_currency

USAGE_PREFERENCES = ("primera_opcion", "si_necesario", "ultimo_recurso")

_EDITABLE = (
    "currency_id", "description", "principal_amount", "usage_preference", "start_date",
    "installment_start_date", "installment_amount", "total_installments", "financing_rate",
    "overdue_rate", "rates_add_vat",
)


def _validate_common(db, user, *, currency_id, description, principal_amount, usage_preference, installment_amount):
    require_user_currency(db, user, currency_id)  # 422 currency_not_available
    if description is None or len(description.strip()) < 8:
        raise AppError(ErrorCode.description_invalid, field="description")
    if principal_amount is None or principal_amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="principal_amount")
    if installment_amount is not None and installment_amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="installment_amount")
    if usage_preference not in USAGE_PREFERENCES:
        raise AppError(ErrorCode.usage_preference_invalid, field="usage_preference")


def _validate_schedule(isd, iamount, total, frate, orate):
    if isd is not None:
        if iamount is None:
            raise AppError(ErrorCode.installments_invalid, field="installment_amount")
        if total is None or total < 1:
            raise AppError(ErrorCode.installments_invalid, field="total_installments")
        for rate, field in ((frate, "financing_rate"), (orate, "overdue_rate")):
            if rate is not None and rate < 0:
                raise AppError(ErrorCode.rates_negative, field=field)
    else:
        for value, field in (
            (iamount, "installment_amount"), (total, "total_installments"),
            (frate, "financing_rate"), (orate, "overdue_rate"),
        ):
            if value is not None:
                raise AppError(ErrorCode.installments_invalid, field=field)


def create_financing(db: Session, user: User, payload: FinancingCreate) -> Financing:
    _validate_common(
        db, user, currency_id=payload.currency_id, description=payload.description,
        principal_amount=payload.principal_amount, usage_preference=payload.usage_preference,
        installment_amount=payload.installment_amount,
    )
    _validate_schedule(
        payload.installment_start_date, payload.installment_amount, payload.total_installments,
        payload.financing_rate, payload.overdue_rate,
    )
    f = Financing(
        user_id=user.id, currency_id=payload.currency_id, description=payload.description,
        principal_amount=payload.principal_amount, usage_preference=payload.usage_preference,
        start_date=payload.start_date, installment_start_date=payload.installment_start_date,
        installment_amount=payload.installment_amount, total_installments=payload.total_installments,
        financing_rate=payload.financing_rate, overdue_rate=payload.overdue_rate,
        rates_add_vat=payload.rates_add_vat,
    )
    db.add(f)
    db.flush()
    db.commit()
    db.refresh(f)
    return f


def list_financings(db: Session, user: User) -> list[Financing]:
    return list(
        db.execute(
            select(Financing).where(Financing.user_id == user.id).order_by(Financing.created_at.desc())
        ).scalars()
    )


def _require_financing(db: Session, user: User, financing_id: uuid.UUID) -> Financing:
    f = db.get(Financing, financing_id)
    if f is None or f.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    return f


def update_financing(db: Session, user: User, financing_id: uuid.UUID, payload: FinancingUpdate) -> Financing:
    f = _require_financing(db, user, financing_id)
    fields = payload.model_fields_set
    if not fields & set(_EDITABLE):
        raise AppError(ErrorCode.empty_patch)

    def final(name):
        return getattr(payload, name) if name in fields else getattr(f, name)

    _validate_common(
        db, user, currency_id=final("currency_id"), description=final("description"),
        principal_amount=final("principal_amount"), usage_preference=final("usage_preference"),
        installment_amount=final("installment_amount"),
    )
    _validate_schedule(
        final("installment_start_date"), final("installment_amount"), final("total_installments"),
        final("financing_rate"), final("overdue_rate"),
    )
    for name in fields & set(_EDITABLE):
        setattr(f, name, getattr(payload, name))
    db.flush()
    db.commit()
    db.refresh(f)
    return f


def delete_financing(db: Session, user: User, financing_id: uuid.UUID) -> None:
    f = _require_financing(db, user, financing_id)
    db.delete(f)
    db.commit()
```

- [ ] **Step 4: Router** `app/routers/financings.py`:

```python
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.financing import FinancingCreate, FinancingOut, FinancingUpdate
from app.services import financing_service as svc

router = APIRouter(tags=["financings"])


@router.post("/financings", response_model=FinancingOut, status_code=status.HTTP_201_CREATED)
def create_financing(
    payload: FinancingCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FinancingOut:
    return FinancingOut.model_validate(svc.create_financing(db, user, payload))


@router.get("/financings")
def list_financings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FinancingOut]:
    return [FinancingOut.model_validate(f) for f in svc.list_financings(db, user)]


@router.patch("/financings/{financing_id}", response_model=FinancingOut)
def update_financing(
    financing_id: uuid.UUID,
    payload: FinancingUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FinancingOut:
    return FinancingOut.model_validate(svc.update_financing(db, user, financing_id, payload))


@router.delete("/financings/{financing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_financing(
    financing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    svc.delete_financing(db, user, financing_id)
```

- [ ] **Step 5: Registrar el router** en `app/main.py` (import + `app.include_router(financings.router)`).

- [ ] **Step 6: Tests POST** `tests/test_financings_create.py`:

```python
from sqlalchemy import select

from app.models.user import User


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


WITH_SCHEDULE = {
    "currency_id": 1, "description": "Préstamo Itaú preaprobado", "principal_amount": "200000.00",
    "usage_preference": "primera_opcion", "start_date": "2026-07-01", "installment_start_date": "2026-08-01",
    "installment_amount": "10500.00", "total_installments": 24, "financing_rate": "72.00",
    "overdue_rate": "85.00", "rates_add_vat": True,
}
NO_SCHEDULE = {
    "currency_id": 1, "description": "Mi viejo me presta", "principal_amount": "50000.00",
    "usage_preference": "si_necesario", "start_date": None,
}


def test_create_with_schedule(client, db_session, seed_uy_currency):
    r = client.post("/financings", json=WITH_SCHEDULE, headers=_headers(client))
    assert r.status_code == 201
    body = r.json()
    assert body["total_installments"] == 24
    assert body["installment_amount"] == "10500.00"
    assert "created_at" not in body


def test_create_without_schedule(client, db_session, seed_uy_currency):
    r = client.post("/financings", json=NO_SCHEDULE, headers=_headers(client))
    assert r.status_code == 201
    assert r.json()["installment_start_date"] is None
    assert r.json()["rates_add_vat"] is True  # default


def test_currency_not_available(client, db_session, seed_uy_currency):
    body = {**NO_SCHEDULE, "currency_id": 999}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "currency_not_available"


def test_description_invalid(client, db_session, seed_uy_currency):
    body = {**NO_SCHEDULE, "description": "corta"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "description_invalid"


def test_amount_invalid(client, db_session, seed_uy_currency):
    body = {**NO_SCHEDULE, "principal_amount": "0"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "amount_invalid"


def test_usage_preference_invalid(client, db_session, seed_uy_currency):
    body = {**NO_SCHEDULE, "usage_preference": "cuando_sea"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "usage_preference_invalid"


def test_schedule_missing_fields(client, db_session, seed_uy_currency):
    # installment_start_date sin installment_amount/total_installments
    body = {**NO_SCHEDULE, "installment_start_date": "2026-08-01"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "installments_invalid"


def test_schedule_total_lt_1(client, db_session, seed_uy_currency):
    body = {**WITH_SCHEDULE, "total_installments": 0}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "installments_invalid"


def test_schedule_columns_without_anchor(client, db_session, seed_uy_currency):
    # sin installment_start_date pero con una columna de cronograma
    body = {**NO_SCHEDULE, "financing_rate": "10.00"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "installments_invalid"


def test_rates_negative(client, db_session, seed_uy_currency):
    body = {**WITH_SCHEDULE, "financing_rate": "-1.00"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "rates_negative"
```

- [ ] **Step 7: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_financings_create.py -q
```

- [ ] **Step 8: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/core/errors.py app/schemas/financing.py app/services/financing_service.py app/routers/financings.py app/main.py tests/test_financings_create.py && git commit -m "feat: POST /financings"
```

---

## Task 3: GET /financings

**Files:** `tests/test_financings_read.py`

- [ ] **Step 1: Tests** (el service + router ya están de Task 2; este task agrega cobertura):

```python
from app.models.user import User


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


BASE = {
    "currency_id": 1, "description": "Mi viejo me presta", "principal_amount": "50000.00",
    "usage_preference": "si_necesario",
}


def test_list_empty(client, db_session, seed_uy_currency):
    assert client.get("/financings", headers=_headers(client)).json() == []


def test_list_orders_newest_first(client, db_session, seed_uy_currency):
    headers = _headers(client)
    client.post("/financings", json={**BASE, "description": "Primera opción"}, headers=headers)
    client.post("/financings", json={**BASE, "description": "Segunda opción"}, headers=headers)
    rows = client.get("/financings", headers=headers).json()
    assert [r["description"] for r in rows] == ["Segunda opción", "Primera opción"]


def test_list_only_own(client, db_session, seed_uy_currency):
    headers_a = _headers(client, email="a@b.com")
    client.post("/financings", json=BASE, headers=headers_a)
    headers_b = _headers(client, email="b@b.com")
    assert client.get("/financings", headers=headers_b).json() == []
```

- [ ] **Step 2: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_financings_read.py -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add tests/test_financings_read.py && git commit -m "test: GET /financings"
```

---

## Task 4: PATCH /financings/{id}

**Files:** `tests/test_financings_update.py`

- [ ] **Step 1: Tests**:

```python
def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


WITH_SCHEDULE = {
    "currency_id": 1, "description": "Préstamo Itaú preaprobado", "principal_amount": "200000.00",
    "usage_preference": "primera_opcion", "installment_start_date": "2026-08-01",
    "installment_amount": "10500.00", "total_installments": 24, "financing_rate": "72.00", "overdue_rate": "85.00",
}
NO_SCHEDULE = {
    "currency_id": 1, "description": "Mi viejo me presta", "principal_amount": "50000.00",
    "usage_preference": "si_necesario",
}


def _create(client, headers, body):
    return client.post("/financings", json=body, headers=headers).json()["id"]


def test_patch_amount_and_description(client, db_session, seed_uy_currency):
    headers = _headers(client)
    fid = _create(client, headers, WITH_SCHEDULE)
    r = client.patch(f"/financings/{fid}", json={"principal_amount": "220000.00", "installment_amount": "11200.00"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["principal_amount"] == "220000.00"
    assert r.json()["installment_amount"] == "11200.00"


def test_patch_add_schedule(client, db_session, seed_uy_currency):
    headers = _headers(client)
    fid = _create(client, headers, NO_SCHEDULE)
    r = client.patch(
        f"/financings/{fid}",
        json={"installment_start_date": "2026-08-01", "installment_amount": "5000.00", "total_installments": 10},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["total_installments"] == 10


def test_patch_remove_schedule(client, db_session, seed_uy_currency):
    headers = _headers(client)
    fid = _create(client, headers, WITH_SCHEDULE)
    r = client.patch(
        f"/financings/{fid}",
        json={"installment_start_date": None, "installment_amount": None, "total_installments": None,
              "financing_rate": None, "overdue_rate": None},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["installment_start_date"] is None
    assert r.json()["financing_rate"] is None


def test_patch_empty(client, db_session, seed_uy_currency):
    headers = _headers(client)
    fid = _create(client, headers, NO_SCHEDULE)
    assert client.patch(f"/financings/{fid}", json={}, headers=headers).json()["code"] == "empty_patch"


def test_patch_inconsistent_final_state(client, db_session, seed_uy_currency):
    # quitar el ancla pero dejar una columna del cronograma -> inconsistente
    headers = _headers(client)
    fid = _create(client, headers, WITH_SCHEDULE)
    r = client.patch(f"/financings/{fid}", json={"installment_start_date": None}, headers=headers)
    assert r.json()["code"] == "installments_invalid"


def test_patch_not_found(client, db_session, seed_uy_currency):
    import uuid
    headers = _headers(client)
    assert client.patch(f"/financings/{uuid.uuid4()}", json={"principal_amount": "1.00"}, headers=headers).status_code == 404
```

- [ ] **Step 2: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_financings_update.py -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add tests/test_financings_update.py && git commit -m "test: PATCH /financings"
```

---

## Task 5: DELETE /financings/{id}

**Files:** `tests/test_financings_delete.py`

- [ ] **Step 1: Tests**:

```python
import uuid

from app.models.financing import Financing


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


BASE = {
    "currency_id": 1, "description": "Mi viejo me presta", "principal_amount": "50000.00",
    "usage_preference": "si_necesario",
}


def test_delete_ok(client, db_session, seed_uy_currency):
    headers = _headers(client)
    fid = client.post("/financings", json=BASE, headers=headers).json()["id"]
    assert client.delete(f"/financings/{fid}", headers=headers).status_code == 204
    assert db_session.get(Financing, uuid.UUID(fid)) is None


def test_delete_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    assert client.delete(f"/financings/{uuid.uuid4()}", headers=headers).status_code == 404


def test_delete_other_user(client, db_session, seed_uy_currency):
    headers_a = _headers(client, email="a@b.com")
    fid = client.post("/financings", json=BASE, headers=headers_a).json()["id"]
    headers_b = _headers(client, email="b@b.com")
    assert client.delete(f"/financings/{fid}", headers=headers_b).status_code == 404
```

- [ ] **Step 2: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_financings_delete.py -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add tests/test_financings_delete.py && git commit -m "feat: DELETE /financings/{id}"
```

---

## Task 6: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (502 previos + los nuevos de financings).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/financings` a `main` (1 commit). Push **manual**.

> Notion ya documenta tabla y endpoints tal cual; no requiere actualización.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** enum + tabla + modelo + migración (Task 1), `usage_preference_invalid` + schemas +
  service (común + cronograma) + POST (Task 2), GET (Task 3), PATCH estado-final con agregar/quitar cronograma
  (Task 4), DELETE aislado (Task 5). Reusa el resto de codes. ✓
- **Placeholder scan:** sin TBD/TODO ni código roto. La migración se genera por autogenerate con checklist de
  verificación (no se puede fijar el `down_revision` de antemano). ✓
- **Consistencia:** `FinancingCreate/Update/Out`; `_validate_common`/`_validate_schedule` compartidos por POST y
  PATCH; `USAGE_PREFERENCES` = enum; `installment_amount ≤ 0 → amount_invalid` (común) vs ausencia →
  `installments_invalid` (cronograma). `FinancingOut.model_validate` (from_attributes). ✓
- **Riesgo conocido:** la migración autogenerada puede no dropear el enum en `downgrade` — el checklist lo cubre
  (agregar `sa.Enum(name='financing_usage').drop(...)`). Tests no dependen de la migración (`create_all`).
