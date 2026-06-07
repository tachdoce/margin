# Tablas `plans` + `plan_movements` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear los modelos SQLAlchemy `Plan` y `PlanMovement` (con sus 2 enums nativos) y la migración Alembic de las tablas `plans` y `plan_movements`, sin endpoints ni validaciones.

**Architecture:** Dos modelos (patrón de `app/models/user.py` para uuid/timestamps y de `obligation_type.py` para `Enum` nativo) registrados en `app/models/__init__.py`. Tablas en `margin_test` vía `create_all` del conftest; en `margin` (dev) vía una migración autogenerada y revisada (crea los 2 enums + ambas tablas; `plans` primero por la FK de `plan_movements`).

**Tech Stack:** SQLAlchemy 2.0 (`Mapped`/`mapped_column`, `Enum`), Alembic, Postgres, pytest. Python 3.13 (`backend/.venv`).

**Spec:** `docs/superpowers/specs/2026-06-07-plans-tablas-design.md`.

**Git:** rama `feat/plans-tablas`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/models/
├── plan.py                 # modelo Plan   (NUEVO)
├── plan_movement.py        # modelo PlanMovement   (NUEVO)
└── __init__.py             # + imports de Plan y PlanMovement   (MODIFICAR)
backend/alembic/versions/
└── xxxx_create_plans_and_plan_movements.py   (NUEVO, autogenerado + revisado)
backend/tests/
└── test_plans_model.py     # round-trip de los 2 modelos   (NUEVO)
```

---

## Task 1: Modelos `Plan` + `PlanMovement` + registro + tests (TDD)

**Files:**
- Create: `backend/app/models/plan.py`, `backend/app/models/plan_movement.py`, `backend/tests/test_plans_model.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Escribir el test que falla `backend/tests/test_plans_model.py`**

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.currency import Currency
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User


def _seed(db_session):
    """Currency UY + un user. Requiere seed_uy (country UY)."""
    db_session.add(Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True))
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    return user


def test_plan_roundtrip_sin_objetivo(db_session, seed_uy):
    user = _seed(db_session)
    plan = Plan(
        user_id=user.id,
        name="Mi plan actual",
        is_default=True,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("0.00"),
        dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.flush()
    db_session.refresh(plan)

    assert plan.id is not None
    assert plan.is_default is True
    assert plan.goal_kind is None
    assert plan.goal_amount is None
    assert plan.goal_currency_id is None
    assert plan.created_at is not None
    assert plan.updated_at is not None


def test_plan_con_objetivo_y_movimiento_prestamo(db_session, seed_uy):
    user = _seed(db_session)
    plan = Plan(
        user_id=user.id,
        name="Plan ahorro",
        is_default=False,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("15000.00"),
        dial_currency_id=1,
        goal_kind="ahorro_total",
        goal_amount=Decimal("100000.00"),
        goal_currency_id=1,
    )
    db_session.add(plan)
    db_session.flush()

    mov = PlanMovement(
        plan_id=plan.id,
        kind="prestamo",
        currency_id=1,
        description="Préstamo Itaú",
        principal_amount=Decimal("50000.00"),
        start_date=date(2026, 8, 1),
        income_duration_months=1,
        installment_amount=Decimal("5000.00"),
        installment_start_date=date(2026, 9, 1),
        total_installments=12,
        financing_rate=Decimal("48.50"),
        overdue_rate=Decimal("60.00"),
        rates_add_vat=True,
    )
    db_session.add(mov)
    db_session.flush()
    db_session.refresh(mov)

    assert mov.id is not None
    assert mov.kind == "prestamo"
    assert mov.total_installments == 12
    assert mov.financing_rate == Decimal("48.50")
    assert plan.goal_kind == "ahorro_total"


def test_plan_movement_nullables(db_session, seed_uy):
    user = _seed(db_session)
    plan = Plan(
        user_id=user.id,
        name="P",
        is_default=False,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("0.00"),
        dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.flush()

    mov = PlanMovement(
        plan_id=plan.id,
        kind="deuda_informal",
        currency_id=1,
        principal_amount=Decimal("3000.00"),
        start_date=date(2026, 7, 1),
        rates_add_vat=True,
    )
    db_session.add(mov)
    db_session.flush()
    db_session.refresh(mov)

    assert mov.description is None
    assert mov.income_duration_months is None
    assert mov.installment_amount is None
    assert mov.installment_start_date is None
    assert mov.total_installments is None
    assert mov.financing_rate is None
    assert mov.overdue_rate is None
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_plans_model.py -v`
Expected: FALLA con `ModuleNotFoundError: No module named 'app.models.plan'`.

- [ ] **Step 3: Crear `backend/app/models/plan.py`**

```python
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_engine_generated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dial_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    dial_currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    goal_kind: Mapped[str | None] = mapped_column(Enum("ahorro_total", name="plan_goal_kind"), nullable=True)
    goal_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    goal_currency_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Crear `backend/app/models/plan_movement.py`**

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PlanMovement(Base):
    __tablename__ = "plan_movements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False)
    kind: Mapped[str] = mapped_column(
        Enum("ingreso", "deuda_informal", "prestamo", name="plan_movement_kind"), nullable=False
    )
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    description: Mapped[str | None] = mapped_column(String(100), nullable=True)
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    income_duration_months: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    installment_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    installment_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_installments: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    financing_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    rates_add_vat: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 5: Registrar los modelos en `backend/app/models/__init__.py`**

Agregar al final del archivo (después de la línea de `Income`):

```python
from app.models.plan import Plan  # noqa: F401
from app.models.plan_movement import PlanMovement  # noqa: F401
```

- [ ] **Step 6: Correr y verificar que pasan**

Run: `pytest tests/test_plans_model.py -v`
Expected: PASAN los 3 tests (el `create_all` del conftest crea los 2 enums y las 2 tablas en `margin_test`).

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/plan.py backend/app/models/plan_movement.py backend/app/models/__init__.py backend/tests/test_plans_model.py
git commit -m "feat(backend): modelos Plan y PlanMovement (con enums nativos) + round-trip"
```

---

## Task 2: Migración Alembic + verificación

**Files:** Create `backend/alembic/versions/<hash>_create_plans_and_plan_movements.py` (autogenerada)

- [ ] **Step 1: Autogenerar la migración**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic revision --autogenerate -m "create plans and plan_movements"`
Expected: crea un archivo con `op.create_table('plans', ...)` y `op.create_table('plan_movements', ...)` (plans primero). El `down_revision` apunta al head actual.

- [ ] **Step 2: Revisar la migración generada**

Confirmar que el `upgrade()` crea ambas tablas con los enums nativos y las FKs. Debe quedar equivalente a:

```python
def upgrade() -> None:
    op.create_table(
        'plans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('is_engine_generated', sa.Boolean(), nullable=False),
        sa.Column('selected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dial_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('dial_currency_id', sa.SmallInteger(), nullable=False),
        sa.Column('goal_kind', sa.Enum('ahorro_total', name='plan_goal_kind'), nullable=True),
        sa.Column('goal_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('goal_currency_id', sa.SmallInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['dial_currency_id'], ['currencies.id'], ),
        sa.ForeignKeyConstraint(['goal_currency_id'], ['currencies.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'plan_movements',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.Enum('ingreso', 'deuda_informal', 'prestamo', name='plan_movement_kind'), nullable=False),
        sa.Column('currency_id', sa.SmallInteger(), nullable=False),
        sa.Column('description', sa.String(length=100), nullable=True),
        sa.Column('principal_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('income_duration_months', sa.SmallInteger(), nullable=True),
        sa.Column('installment_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('installment_start_date', sa.Date(), nullable=True),
        sa.Column('total_installments', sa.SmallInteger(), nullable=True),
        sa.Column('financing_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('overdue_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('rates_add_vat', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ),
        sa.ForeignKeyConstraint(['currency_id'], ['currencies.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
```

**Ajuste obligatorio del `downgrade()`** — Alembic dropea las tablas pero NO los tipos enum nativos; agregarlos a mano después de los `drop_table` (mismo patrón que la migración de `auth_provider`):

```python
def downgrade() -> None:
    op.drop_table('plan_movements')
    op.drop_table('plans')
    sa.Enum(name='plan_movement_kind').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plan_goal_kind').drop(op.get_bind(), checkfirst=True)
```

Si el autogenerate metió comandos ajenos a estas 2 tablas, borrarlos.

- [ ] **Step 3: Aplicar la migración sobre `margin`**

Run: `alembic upgrade head`
Expected: `Running upgrade ... -> <hash>, create plans and plan_movements` sin errores.

- [ ] **Step 4: Verificar por psql**

Run: `psql -d margin -c "\d plans" -c "\d plan_movements" -c "\dT+ plan_goal_kind" -c "\dT+ plan_movement_kind"`
Expected: `plans` (13 columnas + timestamps, 3 FKs: user_id→users, dial_currency_id/goal_currency_id→currencies), `plan_movements` (FKs plan_id→plans, currency_id→currencies), y los 2 enums con sus labels (`ahorro_total`; `ingreso`/`deuda_informal`/`prestamo`).

- [ ] **Step 5: Regresión de la suite completa**

Run: `pytest -q`
Expected: pasan todos (los previos + los 3 de `test_plans_model.py`).

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/alembic/versions/
git commit -m "feat(backend): migración de plans y plan_movements"
```

---

## Notas de cierre

- Al terminar: tablas `plans` y `plan_movements` (+ enums `plan_goal_kind`, `plan_movement_kind`) en `margin` (migradas) y en `margin_test` (create_all), con los modelos registrados. Sin endpoints ni validaciones.
- **Cierre:** squash-merge de `feat/plans-tablas` → un commit `feat: tablas plans y plan_movements` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** modelos `Plan` (13 cols + timestamps) y `PlanMovement` (14 cols + timestamps) del §3/§4 — Task 1 ✓; 2 enums nativos del §2 — en los modelos (`Enum(..., name=...)`) y la migración ✓; sin defaults de BD en booleanos, sin CHECKs, sin UNIQUE parcial en `is_default` (§5) — los modelos no los definen ✓; migración + verificación psql + round-trip + regresión (§6) — Task 2 + Task 1 ✓; registro en `__init__.py` — Task 1 Step 5 ✓; sin endpoints/seed (§7) ✓.
- **Placeholders:** ninguno; código completo en cada paso.
- **Consistencia de tipos:** columnas del modelo `Plan`/`PlanMovement` (Task 1) ↔ columnas de la migración (Task 2) coinciden 1 a 1 (UUID, SmallInteger, Numeric(12,2)/(5,2), String(80)/(100), Boolean, Date, DateTime(tz), Enum nativo); FKs del modelo (`users.id`, `currencies.id`, `plans.id`) ↔ `ForeignKeyConstraint` de la migración; el test usa los mismos nombres de campo; el `downgrade` dropea tablas y luego enums.
```
