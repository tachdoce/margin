# Tabla `incomes` (slice 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear el modelo SQLAlchemy `Income` y la migración Alembic de la tabla `incomes` (slice 1 de Ingresos), sin endpoints ni validaciones.

**Architecture:** Un modelo `Income` (patrón de `app/models/user.py`: uuid PK, FKs, timestamps) registrado en `app/models/__init__.py`. La tabla en `margin_test` la crea el `create_all` del conftest (habilita los tests); la tabla en `margin` (dev) la crea una migración Alembic autogenerada y revisada.

**Tech Stack:** SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, Postgres, pytest. Python 3.13 (`backend/.venv`).

**Spec:** `docs/superpowers/specs/2026-06-06-incomes-tabla-design.md`.

**Git:** rama `feat/incomes-tabla`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/models/
├── income.py              # modelo Income   (NUEVO)
└── __init__.py            # + import de Income   (MODIFICAR)
backend/alembic/versions/
└── xxxx_create_incomes.py # migración (autogenerada + revisada)   (NUEVO)
backend/tests/
└── test_incomes_model.py  # round-trip del modelo   (NUEVO)
```

---

## Task 1: Modelo `Income` + registro + test de round-trip (TDD)

**Files:**
- Create: `backend/app/models/income.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_incomes_model.py`

- [ ] **Step 1: Escribir el test que falla `backend/tests/test_incomes_model.py`**

```python
from datetime import date
from decimal import Decimal

from app.models.currency import Currency
from app.models.income import Income
from app.models.income_type import IncomeType
from app.models.user import User


def _seed_refs(db_session):
    """Siembra las referencias (currency UY, income_type, user) para un Income. Requiere seed_uy (country UY)."""
    db_session.add(Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True))
    db_session.add(IncomeType(id=1, code="sueldo", name="Sueldo", visible=True))
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    return user


def test_income_roundtrip_recurring(db_session, seed_uy):
    user = _seed_refs(db_session)
    income = Income(
        user_id=user.id,
        income_type_id=1,
        currency_id=1,
        amount=Decimal("45000.00"),
        description="Sueldo principal",
        is_monthly_recurring=True,
        payment_day=5,
        shift_weekends=False,
    )
    db_session.add(income)
    db_session.flush()
    db_session.refresh(income)

    assert income.id is not None
    assert income.amount == Decimal("45000.00")
    assert income.payment_day == 5
    assert income.first_income_date is None
    assert income.total_months is None
    assert income.deleted_at is None
    assert income.created_at is not None
    assert income.updated_at is not None


def test_income_roundtrip_fixed_term(db_session, seed_uy):
    user = _seed_refs(db_session)
    income = Income(
        user_id=user.id,
        income_type_id=1,
        currency_id=1,
        amount=Decimal("30000.00"),
        description="Freelance ocasional",
        is_monthly_recurring=False,
        first_income_date=date(2026, 7, 10),
        total_months=1,
        shift_weekends=True,
    )
    db_session.add(income)
    db_session.flush()
    db_session.refresh(income)

    assert income.first_income_date == date(2026, 7, 10)
    assert income.total_months == 1
    assert income.payment_day is None
    assert income.shift_weekends is True
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_incomes_model.py -v`
Expected: FALLA con `ModuleNotFoundError: No module named 'app.models.income'`.

- [ ] **Step 3: Crear el modelo `backend/app/models/income.py`**

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Income(Base):
    __tablename__ = "incomes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    income_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("income_types.id"), nullable=False)
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str] = mapped_column(String(100), nullable=False)
    is_monthly_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payment_day: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    first_income_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_months: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    shift_weekends: Mapped[bool] = mapped_column(Boolean, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Registrar el modelo en `backend/app/models/__init__.py`**

Agregar al final del archivo (después de la línea de `IncomeType`):

```python
from app.models.income import Income  # noqa: F401
```

- [ ] **Step 5: Correr y verificar que pasan**

Run: `pytest tests/test_incomes_model.py -v`
Expected: PASAN los 2 tests (el `create_all` del conftest crea la tabla `incomes` en `margin_test`).

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/income.py backend/app/models/__init__.py backend/tests/test_incomes_model.py
git commit -m "feat(backend): modelo Income (tabla incomes) + test de round-trip"
```

---

## Task 2: Migración Alembic de `incomes` + verificación

**Files:**
- Create: `backend/alembic/versions/<hash>_create_incomes.py` (autogenerada)

- [ ] **Step 1: Autogenerar la migración**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic revision --autogenerate -m "create incomes"`
Expected: crea un archivo nuevo en `alembic/versions/` con `op.create_table('incomes', ...)`. El `down_revision` queda apuntando al head actual automáticamente.

- [ ] **Step 2: Revisar la migración generada**

Abrir el archivo nuevo y confirmar que el `upgrade()` coincide con esto (ajustar si el autogenerate metió algo de más, p. ej. cambios no relacionados):

```python
def upgrade() -> None:
    op.create_table(
        'incomes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('income_type_id', sa.SmallInteger(), nullable=False),
        sa.Column('currency_id', sa.SmallInteger(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('description', sa.String(length=100), nullable=False),
        sa.Column('is_monthly_recurring', sa.Boolean(), nullable=False),
        sa.Column('payment_day', sa.SmallInteger(), nullable=True),
        sa.Column('first_income_date', sa.Date(), nullable=True),
        sa.Column('total_months', sa.SmallInteger(), nullable=True),
        sa.Column('shift_weekends', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['income_type_id'], ['income_types.id'], ),
        sa.ForeignKeyConstraint(['currency_id'], ['currencies.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('incomes')
```

Si el autogenerate incluyó comandos ajenos a `incomes` (de otras tablas), borrarlos: la migración debe crear **solo** la tabla `incomes`.

- [ ] **Step 3: Aplicar la migración sobre `margin`**

Run: `alembic upgrade head`
Expected: `Running upgrade ... -> <hash>, create incomes` sin errores.

- [ ] **Step 4: Verificar el esquema por psql**

Run: `psql -d margin -c "\d incomes"`
Expected: tabla `incomes` con las 14 columnas (tipos correctos, `payment_day`/`first_income_date`/`total_months`/`deleted_at` nullable) y 3 foreign keys (`user_id`→users, `income_type_id`→income_types, `currency_id`→currencies).

- [ ] **Step 5: Regresión de la suite completa**

Run: `pytest -q`
Expected: pasan todos (los previos + los 2 nuevos de `test_incomes_model.py`).

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/alembic/versions/
git commit -m "feat(backend): migración de la tabla incomes"
```

---

## Notas de cierre

- Al terminar: la tabla `incomes` existe en `margin` (migrada) y en `margin_test` (vía create_all), con el modelo `Income` registrado. Sin endpoints ni validaciones (eso es el slice 2).
- **Cierre:** squash-merge de `feat/incomes-tabla` → un commit `feat: tabla incomes` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** modelo `Income` con las 14 columnas del esquema (sección 3 del spec) — Task 1 ✓; `deleted_at` incluida, booleanos sin server_default, sin CHECK constraints (sección 4) — el modelo no define defaults de BD para los booleanos ni checks ✓; migración + verificación psql + round-trip test + regresión (sección 5) — Task 2 + Task 1 ✓; registro en `__init__.py` (sección 2) — Task 1 Step 4 ✓; sin endpoints/seed (fuera de alcance) ✓.
- **Placeholders:** ninguno; código completo en cada paso.
- **Consistencia de tipos:** el modelo `Income` (Task 1) y las columnas de la migración (Task 2) coinciden columna por columna (UUID, SmallInteger, Numeric(12,2), String(100), Boolean, Date, DateTime(timezone=True)); las FKs del modelo (`users.id`, `income_types.id`, `currencies.id`) coinciden con las `ForeignKeyConstraint` de la migración; el test usa los mismos nombres de campo que el modelo.
```
