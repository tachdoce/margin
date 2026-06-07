# Slice 1 — Tablas `cash_flow_entries` + `cash_flow_payments` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear las dos tablas de la línea de tiempo del flujo de caja (`cash_flow_entries` + `cash_flow_payments`) con su enum nativo y su migración, sin endpoints ni motor.

**Architecture:** Dos modelos SQLAlchemy nuevos en `app/models/`, registrados en `app/models/__init__.py`. `cash_flow_entries` lleva el enum nativo `cash_flow_source_type` (7 valores) y un `source_id` polimórfico sin FK. `cash_flow_payments` referencia a `cash_flow_entries` con `ON DELETE CASCADE`. Una migración Alembic crea el enum + ambas tablas. Tests de round-trip sobre `margin_test` (create_all) verifican persistencia, nullables y el cascade.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, Postgres 16, pytest. Python 3.13 (`backend/.venv`).

**Spec:** `docs/superpowers/specs/2026-06-07-cash-flow-tablas-design.md`.

**Git:** rama `feat/cash-flow-tablas`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/models/
├── cash_flow_entry.py     # CashFlowEntry + enum cash_flow_source_type   (NUEVO)
├── cash_flow_payment.py   # CashFlowPayment                              (NUEVO)
└── __init__.py            # registrar ambos modelos para Alembic         (MODIFICAR)
backend/tests/
└── test_cash_flow_model.py  # round-trip + nullables + cascade           (NUEVO)
backend/alembic/versions/
└── <hash>_create_cash_flow_tables.py  # migración                        (NUEVO, autogenerado)
```

---

## Task 1: Modelos + test de round-trip (TDD)

**Files:**
- Create: `backend/app/models/cash_flow_entry.py`
- Create: `backend/app/models/cash_flow_payment.py`
- Create: `backend/tests/test_cash_flow_model.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Crear la rama**

```bash
cd /Users/tachone/proyectos/margin
git checkout -b feat/cash-flow-tablas
```

- [ ] **Step 2: Escribir el test que falla en `backend/tests/test_cash_flow_model.py`**

```python
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.currency import Currency
from app.models.user import User


def _seed(db_session):
    """Currency UY + un user. Requiere seed_uy (country UY)."""
    db_session.add(Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True))
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    return user


def test_cash_flow_entry_ingreso_roundtrip(db_session, seed_uy):
    user = _seed(db_session)
    entry = CashFlowEntry(
        user_id=user.id,
        event_date=date(2026, 7, 5),
        is_income=True,
        amount=Decimal("45000.00"),
        currency_id=1,
        source_type="ingreso",
        source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.flush()
    db_session.refresh(entry)

    assert entry.id is not None
    assert entry.is_income is True
    assert entry.amount == Decimal("45000.00")
    # nullables que un ingreso no usa quedan en NULL
    assert entry.financing_rate is None
    assert entry.overdue_rate is None
    assert entry.issue_year is None
    assert entry.issue_month is None
    assert entry.minimum_payment is None
    assert entry.created_at is not None
    assert entry.updated_at is not None


def test_cash_flow_entry_event_date_nullable(db_session, seed_uy):
    user = _seed(db_session)
    entry = CashFlowEntry(
        user_id=user.id,
        event_date=None,
        is_income=False,
        amount=Decimal("1000.00"),
        currency_id=1,
        source_type="deuda_abierta",
        source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.flush()
    db_session.refresh(entry)
    assert entry.event_date is None


def test_cash_flow_payment_roundtrip_real(db_session, seed_uy):
    user = _seed(db_session)
    entry = CashFlowEntry(
        user_id=user.id,
        event_date=date(2026, 7, 5),
        is_income=True,
        amount=Decimal("45000.00"),
        currency_id=1,
        source_type="ingreso",
        source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.flush()

    payment = CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("45000.00"))
    db_session.add(payment)
    db_session.flush()
    db_session.refresh(payment)

    assert payment.id is not None
    # pago real: plan_id, planned_date y note opcionales en NULL
    assert payment.plan_id is None
    assert payment.planned_date is None
    assert payment.note is None
    assert payment.created_at is not None


def test_cash_flow_payment_cascade_on_entry_delete(db_session, seed_uy):
    user = _seed(db_session)
    entry = CashFlowEntry(
        user_id=user.id,
        event_date=date(2026, 7, 5),
        is_income=True,
        amount=Decimal("45000.00"),
        currency_id=1,
        source_type="ingreso",
        source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.flush()
    payment = CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("100.00"))
    db_session.add(payment)
    db_session.flush()
    payment_id = payment.id

    # borrar la entry borra el payment por ON DELETE CASCADE (cascade de BD)
    db_session.delete(entry)
    db_session.flush()
    db_session.expire_all()  # descarta el identity map para forzar relectura desde la BD

    remaining = db_session.execute(
        select(CashFlowPayment).where(CashFlowPayment.id == payment_id)
    ).scalar_one_or_none()
    assert remaining is None
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_flow_model.py -v`
Expected: FALLA en la colección con `ModuleNotFoundError: No module named 'app.models.cash_flow_entry'` (los modelos todavía no existen).

- [ ] **Step 4: Crear `backend/app/models/cash_flow_entry.py`**

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    SmallInteger,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

CASH_FLOW_SOURCE_TYPES = (
    "gasto",
    "deuda",
    "deuda_abierta",
    "ingreso",
    "plan_movimiento",
    "plan_movimiento_entrada",
    "tarjeta_credito",
)


class CashFlowEntry(Base):
    __tablename__ = "cash_flow_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_income: Mapped[bool] = mapped_column(Boolean, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    financing_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    issue_year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    issue_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    minimum_payment: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    source_type: Mapped[str] = mapped_column(
        Enum(*CASH_FLOW_SOURCE_TYPES, name="cash_flow_source_type"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 5: Crear `backend/app/models/cash_flow_payment.py`**

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CashFlowPayment(Base):
    __tablename__ = "cash_flow_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cash_flow_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cash_flow_entries.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=True)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 6: Registrar ambos modelos en `backend/app/models/__init__.py`**

Agregar al final del archivo (después de `from app.models.plan_movement import PlanMovement`):

```python
from app.models.cash_flow_entry import CashFlowEntry  # noqa: F401
from app.models.cash_flow_payment import CashFlowPayment  # noqa: F401
```

- [ ] **Step 7: Correr el test y verificar que pasa**

Run: `pytest tests/test_cash_flow_model.py -v`
Expected: PASAN los 4 tests (create_all construye las tablas en `margin_test`, incluido el FK con CASCADE).

- [ ] **Step 8: Regresión de la suite completa**

Run: `pytest -q`
Expected: pasan todos.

- [ ] **Step 9: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/cash_flow_entry.py backend/app/models/cash_flow_payment.py backend/app/models/__init__.py backend/tests/test_cash_flow_model.py
git commit -m "feat(backend): modelos cash_flow_entries + cash_flow_payments"
```

---

## Task 2: Migración Alembic

**Files:**
- Create: `backend/alembic/versions/<hash>_create_cash_flow_tables.py` (autogenerado, luego revisado)

- [ ] **Step 1: Autogenerar la migración**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic revision --autogenerate -m "create cash_flow_entries and cash_flow_payments"`
Expected: crea un archivo nuevo en `alembic/versions/`.

- [ ] **Step 2: Revisar el archivo generado**

Abrir el archivo nuevo y confirmar en `upgrade()`:
- `op.create_table('cash_flow_entries', ...)` **antes** que `cash_flow_payments` (por la FK). Si Alembic las ordenó al revés, reordenar manualmente.
- La columna `source_type` usa `sa.Enum('gasto', 'deuda', 'deuda_abierta', 'ingreso', 'plan_movimiento', 'plan_movimiento_entrada', 'tarjeta_credito', name='cash_flow_source_type')`.
- `cash_flow_entries` tiene FKs a `users.id` (`user_id`) y `currencies.id` (`currency_id`), y **NO** tiene FK sobre `source_id`.
- `cash_flow_payments` tiene `sa.ForeignKeyConstraint(['cash_flow_entry_id'], ['cash_flow_entries.id'], ondelete='CASCADE')` y FK a `plans.id` (`plan_id`).
- Nullables correctos: `event_date`, `financing_rate`, `overdue_rate`, `issue_year`, `issue_month`, `minimum_payment` nullable en entries; `note`, `plan_id`, `planned_date` nullable en payments. El resto NOT NULL.

- [ ] **Step 3: Ajustar el `downgrade()` para dropear el enum**

Alembic no dropea el tipo enum nativo solo. Editar `downgrade()` para que quede (las tablas primero, luego el enum):

```python
def downgrade() -> None:
    op.drop_table('cash_flow_payments')
    op.drop_table('cash_flow_entries')
    sa.Enum(name='cash_flow_source_type').drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 4: Aplicar la migración sobre `margin`**

Run: `alembic upgrade head`
Expected: aplica sin error; `alembic current` muestra la nueva revisión como head.

- [ ] **Step 5: Verificar el esquema en Postgres**

Run: `psql -d margin -c "\d cash_flow_entries" -c "\d cash_flow_payments" -c "\dT cash_flow_source_type"`
Expected:
- `cash_flow_entries`: las columnas y tipos del spec; FKs a `users` y `currencies`; sin FK en `source_id`.
- `cash_flow_payments`: FK `cash_flow_entry_id` → `cash_flow_entries(id)` con `ON DELETE CASCADE`; FK `plan_id` → `plans(id)`.
- `cash_flow_source_type`: los 7 labels en orden.

- [ ] **Step 6: Verificar que el downgrade funciona (round-trip de migración)**

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: baja (dropea tablas + enum) y vuelve a subir sin error. Confirma que el `downgrade` quedó correcto.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/alembic/versions/
git commit -m "feat(backend): migración cash_flow_entries + cash_flow_payments"
```

---

## Notas de cierre

- Al terminar: existen las tablas `cash_flow_entries` y `cash_flow_payments` (con su enum) en `margin` y en el esquema de tests, sin endpoints ni motor. Nada más las escribe todavía.
- **Cierre:** squash-merge de `feat/cash-flow-tablas` → un commit `feat: tablas cash_flow_entries + cash_flow_payments` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** enum nativo de 7 valores (§2) — Task 1 Step 4 + Task 2 Step 2 ✓; tabla `cash_flow_entries` con todas las columnas y nullables (§3) — Task 1 Step 4 ✓; tabla `cash_flow_payments` con CASCADE (§4) — Task 1 Step 5 ✓; `source_id` sin FK (§5) — Task 1 Step 4 (sin `ForeignKey`) + Task 2 Step 2 (revisión) ✓; sin `server_default` en `is_income` (§5) — Task 1 Step 4 ✓; migración con enum + orden de tablas + downgrade que dropea el enum (§6) — Task 2 ✓; test round-trip + nullables + cascade (§6) — Task 1 Step 2 ✓; registro en `__init__.py` (§1) — Task 1 Step 6 ✓.
- **Placeholders:** ninguno; código completo en cada step.
- **Consistencia de tipos:** los nombres de columna del modelo (`event_date`, `is_income`, `source_type`, `source_id`, `cash_flow_entry_id`, `plan_id`, `planned_date`) coinciden entre los modelos (Task 1), el test (Task 1 Step 2) y la revisión de la migración (Task 2 Step 2). El enum `cash_flow_source_type` y sus 7 labels son idénticos en el modelo y en la migración. El test usa `User(country_code=..., display_name=...)` y `Currency(id=1, ...)`, igual que `test_plans_model.py`.
```
