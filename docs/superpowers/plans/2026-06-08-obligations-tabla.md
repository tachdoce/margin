# Tabla `obligations` — Plan de implementación

> **For agentic workers:** Ejecutar según el modo que elija el usuario (inline o subagente). TDD: test →
> rojo → implementación → verde → commit por task. Steps con checkbox (`- [ ]`).

**Goal:** Crear la tabla `obligations` (modelo + migración + tests mínimos), la entidad unificada del
subdominio Obligaciones. Solo estructura; sin lógica.

**Architecture:** Modelo SQLAlchemy `app/models/obligation.py` registrado en `__init__.py`, migración
Alembic autogenerada y revisada. Booleans/text NOT NULL sin server_default (los setea el backend en slices
futuros); timestamps con server_default. Sin CHECKs de kind (invariantes del backend). Autoref
`origin_obligation_id` sin cascade.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, Alembic, Postgres. Spec:
`docs/superpowers/specs/2026-06-08-obligations-tabla-design.md`.

**Rama:** `feat/obligations-tabla` → squash-merge a `main`.

---

## Task 0: Crear la rama

- [ ] **Step 1: Crear y cambiar a la rama**

```bash
git checkout -b feat/obligations-tabla
```

---

## Task 1: Modelo `Obligation` + tests

**Files:**
- Create: `backend/app/models/obligation.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_obligations_model.py`

- [ ] **Step 1: Escribir los tests (rojo)**

`backend/tests/test_obligations_model.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.currency import Currency
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.user import User


@pytest.fixture
def refs(db_session, seed_uy_currency):
    """Siembra priority_levels, obligation_types (1 por kind) y un usuario. Devuelve el usuario."""
    db_session.add_all(
        [
            PriorityLevel(level=2, name="Esencial", description="x"),
            PriorityLevel(level=4, name="Obligación prioritaria", description="x"),
            PriorityLevel(level=6, name="Ajustable", description="x"),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                           description="x", default_priority_level=2, visible=True),
            ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                           description="x", default_priority_level=4, visible=True),
            ObligationType(id=8, obligation_kind="deuda_abierta", code="informal", name="Informal",
                           description="x", default_priority_level=6, visible=True),
        ]
    )
    db_session.flush()
    user = User(country_code="UY")
    db_session.add(user)
    db_session.flush()
    return user


def _base_kwargs(user):
    """Campos NOT NULL comunes a toda obligación."""
    return dict(
        user_id=user.id,
        currency_id=1,
        amount=Decimal("45000.00"),
        is_monthly_recurring=False,
        shift_weekends=False,
        rates_add_vat=True,
        is_closed=False,
        review_findings="[]",
        is_ready=False,
    )


def test_insert_gasto_recurrente(db_session, refs):
    user = refs
    o = Obligation(
        **_base_kwargs(user),
        obligation_type_id=1,
        priority_level=2,
        due_day=5,
    )
    o.is_monthly_recurring = True  # _base_kwargs lo trae en False; lo sobrescribimos
    db_session.add(o)
    db_session.flush()
    db_session.refresh(o)
    assert o.id is not None
    assert o.due_day == 5
    assert o.created_at is not None


def test_insert_deuda_con_cronograma(db_session, refs):
    user = refs
    o = Obligation(
        **_base_kwargs(user),
        obligation_type_id=10,
        priority_level=4,
        due_day=10,
        total_installments=12,
        first_due_date=date(2026, 8, 1),
        financing_rate=Decimal("3.50"),
        overdue_rate=Decimal("5.00"),
    )
    db_session.add(o)
    db_session.flush()
    db_session.refresh(o)
    assert o.total_installments == 12
    assert o.financing_rate == Decimal("3.50")


def test_insert_deuda_abierta(db_session, refs):
    user = refs
    o = Obligation(
        **_base_kwargs(user),
        obligation_type_id=8,
        priority_level=6,
    )
    db_session.add(o)
    db_session.flush()
    db_session.refresh(o)
    assert o.first_due_date is None
    assert o.financing_rate is None


def test_invalid_obligation_type_fk(db_session, refs):
    user = refs
    o = Obligation(**_base_kwargs(user), obligation_type_id=999, priority_level=2)
    db_session.add(o)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_self_reference_origin(db_session, refs):
    user = refs
    parent = Obligation(**_base_kwargs(user), obligation_type_id=10, priority_level=4)
    db_session.add(parent)
    db_session.flush()
    child = Obligation(
        **_base_kwargs(user), obligation_type_id=10, priority_level=4,
        origin_obligation_id=parent.id,
    )
    db_session.add(child)
    db_session.flush()
    db_session.refresh(child)
    assert child.origin_obligation_id == parent.id


def test_not_null_amount(db_session, refs):
    user = refs
    kwargs = _base_kwargs(user)
    del kwargs["amount"]
    o = Obligation(**kwargs, obligation_type_id=1, priority_level=2)
    db_session.add(o)
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: Correr los tests, verificar que fallan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_obligations_model.py -q
```
Esperado: FAIL (ModuleNotFoundError: app.models.obligation).

- [ ] **Step 3: Crear el modelo**

`backend/app/models/obligation.py`:

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Obligation(Base):
    __tablename__ = "obligations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    obligation_type_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("obligation_types.id"), nullable=False
    )
    priority_level: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("priority_levels.level"), nullable=False
    )
    institution_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("institutions.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_monthly_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False)
    due_day: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_installments: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    first_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shift_weekends: Mapped[bool] = mapped_column(Boolean, nullable=False)
    financing_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    rates_add_vat: Mapped[bool] = mapped_column(Boolean, nullable=False)
    origin_obligation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("obligations.id"), nullable=True, index=True
    )
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_findings: Mapped[str] = mapped_column(Text, nullable=False)
    user_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Registrar el modelo en `__init__.py`**

En `backend/app/models/__init__.py`, agregar (después de la línea de `plan_movement`, antes de
`cash_flow_entry`):
```python
from app.models.obligation import Obligation  # noqa: F401
```

- [ ] **Step 5: Correr los tests, verificar que pasan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_obligations_model.py -q
```
Esperado: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/obligation.py backend/app/models/__init__.py backend/tests/test_obligations_model.py
git commit -m "feat: modelo Obligation (tabla obligations)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Migración Alembic

**Files:**
- Create: `backend/alembic/versions/<hash>_create_obligations.py` (autogenerada)

- [ ] **Step 1: Autogenerar la migración**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic revision --autogenerate -m "create obligations"
```

- [ ] **Step 2: Revisar la migración generada**

Abrir el archivo nuevo en `alembic/versions/`. Verificar:
- `op.create_table('obligations', ...)` con todas las columnas de §2 del spec, tipos correctos
  (`UUID`, `SmallInteger`, `Numeric(12,2)`/`Numeric(5,2)`, `Date`, `Text`, `DateTime(timezone=True)`).
- Las 6 FKs presentes, **incluida la autoref** `origin_obligation_id → obligations.id`.
- Los 2 índices: `user_id` y `origin_obligation_id`.
- El enum `obligation_kind` **no** se crea ni dropea (no es columna de esta tabla; si el autogenerate lo
  toca, quitarlo).
- `downgrade()` hace `op.drop_table('obligations')` (no debe dropear el enum).

Ajustar a mano lo que el autogenerate no haya tomado bien.

- [ ] **Step 3: Aplicar la migración**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic upgrade head
```
Esperado: corre sin error; crea la tabla `obligations` en `margin`.

- [ ] **Step 4: Verificar la tabla en la DB**

```bash
psql -d margin -c "\d obligations"
```
Esperado: la tabla con sus columnas, FKs e índices.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat: migración create obligations

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Suite completa

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```
Esperado: PASS (todo verde, incluidos los 6 nuevos).

---

## Cierre

Tras Task 3 verde: **finishing-a-development-branch** → squash-merge `feat/obligations-tabla` a `main` →
push (manual/prompteado).
