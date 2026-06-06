# Catálogos (credit_card_networks, credit_card_item_types, obligation_types, income_types) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear las 4 tablas de catálogo restantes (modelos + migraciones + seeds) para destrabar obligations, incomes y tarjetas de crédito.

**Architecture:** Una tabla por task: modelo en `app/models/`, registro en `app/models/__init__.py`, migración Alembic con seed (`op.bulk_insert`), verificación por `psql`. `obligation_types` crea además el enum nativo `obligation_kind`. Sin endpoints ni tests nuevos.

**Tech Stack:** FastAPI/SQLAlchemy 2.0/Alembic/Postgres 16, Python 3.13 (`backend/.venv`).

**Spec:** `docs/superpowers/specs/2026-06-06-catalogos-design.md`.

**Git:** rama `feat/catalog-tables`, un commit por tabla, **squash-merge** a un commit en `main`.

---

## Estructura de archivos

```
backend/app/models/
├── __init__.py                  # registrar los 4 modelos nuevos   (MODIFICAR)
├── credit_card_network.py        # CreditCardNetwork    (NUEVO)
├── credit_card_item_type.py       # CreditCardItemType   (NUEVO)
├── obligation_type.py             # ObligationType (+ enum)  (NUEVO)
└── income_type.py                 # IncomeType           (NUEVO)
backend/alembic/versions/          # 4 migraciones nuevas
```

Dependencias: `credit_card_networks`→countries, `obligation_types`→priority_levels (ambas ya existen). Sin orden interno obligatorio.

---

## Task 1: credit_card_networks

**Files:** Create `backend/app/models/credit_card_network.py`, Modify `backend/app/models/__init__.py`, Create migración.

- [ ] **Step 1: `backend/app/models/credit_card_network.py`**

```python
from sqlalchemy import ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CreditCardNetwork(Base):
    __tablename__ = "credit_card_networks"
    __table_args__ = (
        UniqueConstraint("country_code", "code", name="uq_credit_card_networks_country_code_code"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    country_code: Mapped[str] = mapped_column(String(2), ForeignKey("countries.code"), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
```

- [ ] **Step 2: Registrar en `backend/app/models/__init__.py`**

```python
from app.models.credit_card_network import CreditCardNetwork  # noqa: F401
```

- [ ] **Step 3: Autogenerar migración**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic revision --autogenerate -m "create credit_card_networks"`

- [ ] **Step 4: Seed en el `upgrade()`** (después del `op.create_table`)

```python
    op.bulk_insert(
        sa.table(
            "credit_card_networks",
            sa.column("id", sa.SmallInteger),
            sa.column("country_code", sa.String),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
        ),
        [
            {"id": 1, "country_code": "UY", "code": "visa", "name": "Visa"},
            {"id": 2, "country_code": "UY", "code": "mastercard", "name": "Mastercard"},
            {"id": 3, "country_code": "UY", "code": "amex", "name": "Amex"},
            {"id": 4, "country_code": "UY", "code": "oca", "name": "OCA"},
            {"id": 5, "country_code": "UY", "code": "diners", "name": "Diners"},
            {"id": 6, "country_code": "UY", "code": "cabal", "name": "Cabal"},
        ],
    )
```

- [ ] **Step 5: Aplicar y verificar**

Run: `alembic upgrade head && psql -d margin -tAc "select id, code, name from credit_card_networks order by id;"`
Expected: 6 filas (1 visa Visa … 6 cabal Cabal).

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/credit_card_network.py backend/app/models/__init__.py backend/alembic/versions
git commit -m "feat(backend): tabla credit_card_networks con seed UY"
```

---

## Task 2: credit_card_item_types

**Files:** Create `backend/app/models/credit_card_item_type.py`, Modify `backend/app/models/__init__.py`, Create migración.

- [ ] **Step 1: `backend/app/models/credit_card_item_type.py`**

```python
from sqlalchemy import SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CreditCardItemType(Base):
    __tablename__ = "credit_card_item_types"
    __table_args__ = (UniqueConstraint("code", name="uq_credit_card_item_types_code"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
```

- [ ] **Step 2: Registrar en `__init__.py`**

```python
from app.models.credit_card_item_type import CreditCardItemType  # noqa: F401
```

- [ ] **Step 3: Autogenerar**

Run: `alembic revision --autogenerate -m "create credit_card_item_types"`

- [ ] **Step 4: Seed**

```python
    op.bulk_insert(
        sa.table(
            "credit_card_item_types",
            sa.column("id", sa.SmallInteger),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("description", sa.String),
        ),
        [
            {"id": 1, "code": "compra", "name": "Compra", "description": "Un consumo común con la tarjeta: bienes o servicios adquiridos por el usuario."},
            {"id": 2, "code": "interes", "name": "Interés", "description": "Cargo por financiación o mora generado por el saldo de la tarjeta."},
            {"id": 3, "code": "suscripcion", "name": "Suscripción", "description": "Un cargo recurrente por un servicio que se renueva periódicamente."},
        ],
    )
```

- [ ] **Step 5: Aplicar y verificar**

Run: `alembic upgrade head && psql -d margin -tAc "select id, code, name from credit_card_item_types order by id;"`
Expected: 3 filas (compra, interes, suscripcion).

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/credit_card_item_type.py backend/app/models/__init__.py backend/alembic/versions
git commit -m "feat(backend): tabla credit_card_item_types con seed"
```

---

## Task 3: obligation_types (con enum obligation_kind)

**Files:** Create `backend/app/models/obligation_type.py`, Modify `backend/app/models/__init__.py`, Create migración.

- [ ] **Step 1: `backend/app/models/obligation_type.py`**

```python
from sqlalchemy import Boolean, Enum, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ObligationType(Base):
    __tablename__ = "obligation_types"
    __table_args__ = (UniqueConstraint("code", name="uq_obligation_types_code"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    obligation_kind: Mapped[str] = mapped_column(
        Enum("gasto", "deuda", "deuda_abierta", name="obligation_kind"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    default_priority_level: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("priority_levels.level"), nullable=False
    )
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
```

- [ ] **Step 2: Registrar en `__init__.py`**

```python
from app.models.obligation_type import ObligationType  # noqa: F401
```

- [ ] **Step 3: Autogenerar**

Run: `alembic revision --autogenerate -m "create obligation_types"`
Expected: crea la tabla y el tipo `obligation_kind`.

- [ ] **Step 4: Revisar el enum + agregar el seed**

Confirmar que el `upgrade()` crea el enum `obligation_kind` (vía `sa.Enum(..., name='obligation_kind')` en el `create_table`). En el `downgrade()`, después del `drop_table`, agregar el drop del tipo:

```python
    sa.Enum(name="obligation_kind").drop(op.get_bind(), checkfirst=True)
```

Seed en el `upgrade()` (después del `create_table`):

```python
    op.bulk_insert(
        sa.table(
            "obligation_types",
            sa.column("id", sa.SmallInteger),
            sa.column("obligation_kind", sa.String),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("description", sa.String),
            sa.column("default_priority_level", sa.SmallInteger),
            sa.column("visible", sa.Boolean),
        ),
        [
            {"id": 1, "obligation_kind": "gasto", "code": "alquiler", "name": "Alquiler / hipoteca", "description": "El techo donde vivís: alquiler o cuota de la hipoteca.", "default_priority_level": 2, "visible": True},
            {"id": 2, "obligation_kind": "gasto", "code": "utilities", "name": "Servicios básicos", "description": "Lo que no podés cortar: luz, agua, gas, internet.", "default_priority_level": 2, "visible": True},
            {"id": 3, "obligation_kind": "gasto", "code": "salud", "name": "Salud", "description": "Mutualista, medicación, emergencia móvil.", "default_priority_level": 2, "visible": True},
            {"id": 4, "obligation_kind": "gasto", "code": "subscriptions", "name": "Suscripciones", "description": "Servicios que se debitan solos: streaming, gimnasio, apps.", "default_priority_level": 6, "visible": True},
            {"id": 5, "obligation_kind": "gasto", "code": "otros_gastos", "name": "Otros gastos", "description": "Cualquier gasto que no encaje en los anteriores.", "default_priority_level": 6, "visible": True},
            {"id": 6, "obligation_kind": "deuda", "code": "adelanto_sueldo", "name": "Adelanto de sueldo", "description": "Pediste plata a cuenta del próximo sueldo; el empleador la descuenta cuando cobrás. La carga el sistema, no vos.", "default_priority_level": 1, "visible": True},
            {"id": 7, "obligation_kind": "deuda", "code": "atraso", "name": "Atraso u obligación", "description": "Algo que se atrasó y se acumula solo: impuestos, servicios o alquiler vencidos, multas.", "default_priority_level": 3, "visible": True},
            {"id": 8, "obligation_kind": "deuda_abierta", "code": "informal", "name": "Deuda informal", "description": "Le debés a una persona: familiar, amigo, fiado. Sin cronograma fijo de pagos; pagás cuando podés.", "default_priority_level": 5, "visible": True},
            {"id": 9, "obligation_kind": "deuda", "code": "otras_deudas", "name": "Otra deuda", "description": "Cualquier deuda que no encaje claro en las anteriores.", "default_priority_level": 5, "visible": True},
            {"id": 10, "obligation_kind": "deuda", "code": "prestamo", "name": "Préstamo en cuotas", "description": "Tiene un fin conocido: préstamo personal, de auto, hipoteca o compra en cuotas.", "default_priority_level": 5, "visible": True},
        ],
    )
```

- [ ] **Step 5: Aplicar y verificar**

Run:
```bash
alembic upgrade head && \
psql -d margin -tAc "select count(*) from obligation_types;" && \
psql -d margin -tAc "select enumlabel from pg_enum join pg_type on pg_type.oid=enumtypid where typname='obligation_kind' order by enumsortorder;"
```
Expected: `10`; y el enum imprime `gasto`, `deuda`, `deuda_abierta`.

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/obligation_type.py backend/app/models/__init__.py backend/alembic/versions
git commit -m "feat(backend): tabla obligation_types con enum obligation_kind y seed"
```

---

## Task 4: income_types

**Files:** Create `backend/app/models/income_type.py`, Modify `backend/app/models/__init__.py`, Create migración.

- [ ] **Step 1: `backend/app/models/income_type.py`**

```python
from sqlalchemy import Boolean, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class IncomeType(Base):
    __tablename__ = "income_types"
    __table_args__ = (UniqueConstraint("code", name="uq_income_types_code"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
```

- [ ] **Step 2: Registrar en `__init__.py`**

```python
from app.models.income_type import IncomeType  # noqa: F401
```

- [ ] **Step 3: Autogenerar**

Run: `alembic revision --autogenerate -m "create income_types"`

- [ ] **Step 4: Seed**

```python
    op.bulk_insert(
        sa.table(
            "income_types",
            sa.column("id", sa.SmallInteger),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("visible", sa.Boolean),
        ),
        [
            {"id": 1, "code": "sueldo", "name": "Sueldo", "visible": True},
            {"id": 2, "code": "pension", "name": "Pensión / jubilación", "visible": True},
            {"id": 3, "code": "alquiler", "name": "Alquiler que cobra", "visible": True},
            {"id": 4, "code": "freelance", "name": "Freelance", "visible": True},
            {"id": 5, "code": "comisiones", "name": "Comisiones", "visible": True},
            {"id": 6, "code": "horas_extra", "name": "Horas extra", "visible": True},
            {"id": 7, "code": "aguinaldo", "name": "Aguinaldo", "visible": True},
            {"id": 8, "code": "devolucion_impuestos", "name": "Devolución de impuestos", "visible": True},
            {"id": 9, "code": "otro", "name": "Otro", "visible": True},
        ],
    )
```

- [ ] **Step 5: Aplicar y verificar**

Run: `alembic upgrade head && psql -d margin -tAc "select id, code, name from income_types order by id;"`
Expected: 9 filas (sueldo … otro).

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/income_type.py backend/app/models/__init__.py backend/alembic/versions
git commit -m "feat(backend): tabla income_types con seed"
```

---

## Task 5: Verificación de regresión

**Files:** ninguno.

- [ ] **Step 1: Suite completa**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q`
Expected: pasan todos los tests existentes (16). El harness hace `create_all` sobre `margin_test` con las 4 tablas nuevas (y el enum) sin problema.

- [ ] **Step 2: Conteos en `margin`**

Run:
```bash
psql -d margin -tAc "select 'credit_card_networks', count(*) from credit_card_networks
  union all select 'credit_card_item_types', count(*) from credit_card_item_types
  union all select 'obligation_types', count(*) from obligation_types
  union all select 'income_types', count(*) from income_types;"
```
Expected: credit_card_networks 6, credit_card_item_types 3, obligation_types 10, income_types 9.

---

## Notas de cierre

- Al terminar: las 4 tablas existen, migradas y sembradas; destraban obligations (obligation_types), incomes (income_types) y tarjetas (credit_card_networks, credit_card_item_types).
- **Cierre:** squash-merge de `feat/catalog-tables` → un commit `feat: catálogos` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** credit_card_networks + UNIQUE(country_code, code) (T1) ✓; credit_card_item_types (T2) ✓; obligation_types + enum + FK priority_levels + seed 10 (T3) ✓; income_types (T4) ✓; ids fijos ✓; sin endpoints/tests ✓; verificación psql + pytest (T5) ✓.
- **Placeholders:** ninguno; modelos y seeds completos con textos exactos de Notion.
- **Consistencia:** nombres tabla/columna idénticos entre modelo, seed (`sa.column`) y verificación; el enum `obligation_kind` se crea en upgrade y se dropea en downgrade; FK `default_priority_level`→`priority_levels.level` (que existe, 1–6); seeds de obligation_types usan niveles 1,2,3,5,6 (todos presentes).
