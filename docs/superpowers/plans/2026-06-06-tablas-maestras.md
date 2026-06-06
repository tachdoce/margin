# Tablas maestras — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear las 5 tablas maestras restantes (modelos SQLAlchemy + migraciones Alembic + seeds) para destrabar las FKs de las features que las referencian.

**Architecture:** Una tabla por task: modelo en `app/models/`, registro en `app/models/__init__.py`, migración Alembic autogenerada con su seed (`op.bulk_insert`), verificación por `psql`. Sin endpoints (se sirven por `GET /bootstrap` después) ni tests automatizados nuevos (catálogos sin lógica; se verifica esquema + seed por `psql`).

**Tech Stack:** FastAPI/SQLAlchemy 2.0/Alembic/Postgres 16, Python 3.13 (`backend/.venv`).

**Spec:** `docs/superpowers/specs/2026-06-06-tablas-maestras-design.md`.

**Estrategia de Git:** rama `feat/master-tables`, un commit por tabla, **squash-merge** a un commit en `main`.

> **Refinamiento vs spec:** el spec menciona "1 migración"; el plan usa **una migración por tabla** (estándar de Alembic + permite verificar cada commit por separado). Igual squashean a un PR.

---

## Estructura de archivos

```
backend/app/models/
├── __init__.py            # registrar los 5 modelos nuevos   (MODIFICAR)
├── currency.py            # Currency               (NUEVO)
├── currency_rate.py        # CurrencyRate            (NUEVO)
├── priority_level.py       # PriorityLevel           (NUEVO)
├── institution.py          # Institution             (NUEVO)
└── review_finding_code.py  # ReviewFindingCode       (NUEVO)
backend/alembic/versions/   # 5 migraciones nuevas (una por tabla)
```

Orden (FK): `currencies` → `currency_rates`; `institutions`, `priority_levels`, `review_finding_codes` independientes (solo `currencies`/`institutions` referencian `countries`, que ya existe).

---

## Task 1: currencies

**Files:** Create `backend/app/models/currency.py`, Modify `backend/app/models/__init__.py`, Create migración.

- [ ] **Step 1: `backend/app/models/currency.py`**

```python
from sqlalchemy import Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Currency(Base):
    __tablename__ = "currencies"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    country_code: Mapped[str] = mapped_column(String(2), ForeignKey("countries.code"), nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    is_legal_tender: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    allowed_in_credit_card: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
```

- [ ] **Step 2: Registrar en `backend/app/models/__init__.py`**

Agregar la línea:

```python
from app.models.currency import Currency  # noqa: F401
```

- [ ] **Step 3: Autogenerar migración**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic revision --autogenerate -m "create currencies"`
Expected: archivo nuevo con `op.create_table('currencies', ...)`.

- [ ] **Step 4: Agregar el seed al `upgrade()` de esa migración**

Después del `op.create_table(...)`:

```python
    op.bulk_insert(
        sa.table(
            "currencies",
            sa.column("id", sa.SmallInteger),
            sa.column("country_code", sa.String),
            sa.column("name", sa.String),
            sa.column("is_legal_tender", sa.Boolean),
            sa.column("allowed_in_credit_card", sa.Boolean),
        ),
        [
            {"id": 1, "country_code": "UY", "name": "Peso", "is_legal_tender": True, "allowed_in_credit_card": True},
            {"id": 2, "country_code": "UY", "name": "Dólar compra", "is_legal_tender": False, "allowed_in_credit_card": False},
            {"id": 3, "country_code": "UY", "name": "Dólar", "is_legal_tender": False, "allowed_in_credit_card": True},
            {"id": 4, "country_code": "UY", "name": "Unidad Indexada", "is_legal_tender": False, "allowed_in_credit_card": False},
            {"id": 5, "country_code": "UY", "name": "Unidad Reajustable", "is_legal_tender": False, "allowed_in_credit_card": False},
        ],
    )
```

- [ ] **Step 5: Aplicar y verificar**

Run: `alembic upgrade head && psql -d margin -tAc "select id, name, is_legal_tender from currencies order by id;"`
Expected: 5 filas; `1|Peso|t`, el resto `|f`.

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/currency.py backend/app/models/__init__.py backend/alembic/versions
git commit -m "feat(backend): tabla currencies con seed UY"
```

---

## Task 2: currency_rates (con seed generado)

**Files:** Create `backend/app/models/currency_rate.py`, Modify `backend/app/models/__init__.py`, Create migración.

- [ ] **Step 1: `backend/app/models/currency_rate.py`**

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CurrencyRate(Base):
    __tablename__ = "currency_rates"

    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    is_projected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
```

- [ ] **Step 2: Registrar en `backend/app/models/__init__.py`**

```python
from app.models.currency_rate import CurrencyRate  # noqa: F401
```

- [ ] **Step 3: Autogenerar migración**

Run: `alembic revision --autogenerate -m "create currency_rates"`
Expected: archivo con `op.create_table('currency_rates', ...)` y PK compuesta (`currency_id`, `rate_date`).

- [ ] **Step 4: Agregar el seed GENERADO al `upgrade()`**

Al tope del archivo de migración, junto a los imports, agregar:

```python
from datetime import date, timedelta
from decimal import Decimal
```

Y después del `op.create_table(...)`:

```python
    rates = {2: "39", 3: "41", 4: "6.55", 5: "1921.36"}
    table = sa.table(
        "currency_rates",
        sa.column("currency_id", sa.SmallInteger),
        sa.column("rate_date", sa.Date),
        sa.column("value", sa.Numeric),
        sa.column("is_projected", sa.Boolean),
    )
    rows = []
    current = date(2026, 4, 1)
    end = date(2027, 12, 31)
    while current <= end:
        for currency_id, value in rates.items():
            rows.append(
                {
                    "currency_id": currency_id,
                    "rate_date": current,
                    "value": Decimal(value),
                    "is_projected": True,
                }
            )
        current += timedelta(days=1)
    op.bulk_insert(table, rows)
```

- [ ] **Step 5: Aplicar y verificar**

Run: `alembic upgrade head && psql -d margin -tAc "select count(*) from currency_rates;" && psql -d margin -tAc "select distinct value from currency_rates where currency_id=4;"`
Expected: `2560` y `6.550000`.

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/currency_rate.py backend/app/models/__init__.py backend/alembic/versions
git commit -m "feat(backend): tabla currency_rates con seed de proyección (2026-04 a 2027-12)"
```

---

## Task 3: priority_levels

**Files:** Create `backend/app/models/priority_level.py`, Modify `backend/app/models/__init__.py`, Create migración.

- [ ] **Step 1: `backend/app/models/priority_level.py`**

```python
from sqlalchemy import SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PriorityLevel(Base):
    __tablename__ = "priority_levels"

    level: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
```

- [ ] **Step 2: Registrar en `backend/app/models/__init__.py`**

```python
from app.models.priority_level import PriorityLevel  # noqa: F401
```

- [ ] **Step 3: Autogenerar migración**

Run: `alembic revision --autogenerate -m "create priority_levels"`

- [ ] **Step 4: Agregar el seed al `upgrade()`**

```python
    op.bulk_insert(
        sa.table(
            "priority_levels",
            sa.column("level", sa.SmallInteger),
            sa.column("name", sa.String),
            sa.column("description", sa.String),
        ),
        [
            {"level": 1, "name": "Ineludible", "description": "No pasa por tu decisión: se descuenta solo (ej. adelanto de sueldo que el empleador retiene del próximo cobro). Lo asigna el sistema, no se elige."},
            {"level": 2, "name": "Esencial", "description": "Sin esto no podés vivir ni funcionar: techo, comida, salud, luz, agua, transporte."},
            {"level": 3, "name": "Obligación crítica", "description": "Si no lo pagás, te embargan o te cortan: impuestos atrasados, deuda en mora."},
            {"level": 4, "name": "Obligación prioritaria", "description": "Crece rápido o conviene cubrirla cuanto antes: préstamo con tasa alta."},
            {"level": 5, "name": "Obligación manejable", "description": "Tenés que pagarla pero no te asfixia: interés bajo, o algo que le debés a alguien de confianza."},
            {"level": 6, "name": "Ajustable", "description": "Está en tus manos moverlo o achicarlo: suscripciones y gastos personales."},
        ],
    )
```

- [ ] **Step 5: Aplicar y verificar**

Run: `alembic upgrade head && psql -d margin -tAc "select level, name from priority_levels order by level;"`
Expected: 6 filas (1 Ineludible … 6 Ajustable).

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/priority_level.py backend/app/models/__init__.py backend/alembic/versions
git commit -m "feat(backend): tabla priority_levels con seed"
```

---

## Task 4: institutions

**Files:** Create `backend/app/models/institution.py`, Modify `backend/app/models/__init__.py`, Create migración.

- [ ] **Step 1: `backend/app/models/institution.py`**

```python
from sqlalchemy import Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    country_code: Mapped[str] = mapped_column(String(2), ForeignKey("countries.code"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
```

- [ ] **Step 2: Registrar en `backend/app/models/__init__.py`**

```python
from app.models.institution import Institution  # noqa: F401
```

- [ ] **Step 3: Autogenerar migración**

Run: `alembic revision --autogenerate -m "create institutions"`

- [ ] **Step 4: Agregar el seed al `upgrade()`**

```python
    op.bulk_insert(
        sa.table(
            "institutions",
            sa.column("id", sa.SmallInteger),
            sa.column("country_code", sa.String),
            sa.column("name", sa.String),
            sa.column("visible", sa.Boolean),
        ),
        [
            {"id": 1, "country_code": "UY", "name": "BROU", "visible": True},
            {"id": 2, "country_code": "UY", "name": "Itaú", "visible": True},
            {"id": 3, "country_code": "UY", "name": "Santander", "visible": True},
            {"id": 4, "country_code": "UY", "name": "Scotiabank", "visible": True},
            {"id": 5, "country_code": "UY", "name": "OCA", "visible": True},
        ],
    )
```

- [ ] **Step 5: Aplicar y verificar**

Run: `alembic upgrade head && psql -d margin -tAc "select id, name, visible from institutions order by id;"`
Expected: 5 filas, todas `|t`.

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/institution.py backend/app/models/__init__.py backend/alembic/versions
git commit -m "feat(backend): tabla institutions con seed UY"
```

---

## Task 5: review_finding_codes

**Files:** Create `backend/app/models/review_finding_code.py`, Modify `backend/app/models/__init__.py`, Create migración.

- [ ] **Step 1: `backend/app/models/review_finding_code.py`**

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ReviewFindingCode(Base):
    __tablename__ = "review_finding_codes"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    message: Mapped[str] = mapped_column(String(200), nullable=False)
```

- [ ] **Step 2: Registrar en `backend/app/models/__init__.py`**

```python
from app.models.review_finding_code import ReviewFindingCode  # noqa: F401
```

- [ ] **Step 3: Autogenerar migración**

Run: `alembic revision --autogenerate -m "create review_finding_codes"`

- [ ] **Step 4: Agregar el seed al `upgrade()`**

```python
    op.bulk_insert(
        sa.table(
            "review_finding_codes",
            sa.column("code", sa.String),
            sa.column("message", sa.String),
        ),
        [
            {"code": "amount_above_threshold", "message": "El monto parece muy alto, ¿lo cargaste bien?"},
            {"code": "overdue_lower_than_financing", "message": "La tasa punitoria es menor que la de financiación, ¿es correcto?"},
            {"code": "rate_above_threshold", "message": "Una de las tasas parece muy alta, ¿la cargaste bien?"},
            {"code": "rates_not_updated", "message": "El resumen no trae alguna de las tasas de interés/mora o si incluyen IVA. Esos datos no se actualizarán en la tarjeta al promover; se mantienen los actuales."},
            {"code": "closing_after_due", "message": "La fecha de cierre es posterior a la de vencimiento, ¿las cargaste bien?"},
            {"code": "due_date_in_future", "message": "La fecha de vencimiento está muy adelante en el tiempo, ¿la cargaste bien?"},
            {"code": "due_date_too_old", "message": "La fecha de vencimiento es muy vieja, ¿la cargaste bien?"},
            {"code": "new_card", "message": "Este resumen no corresponde a ninguna tarjeta tuya: al confirmar se va a dar de alta una tarjeta nueva."},
            {"code": "closing_day_inferred", "message": "Pusimos el día de cierre por vos a partir del resumen. Ajustalo si tu tarjeta cierra otro día."},
            {"code": "closing_day_changed", "message": "El día de cierre de este resumen difiere del de tu tarjeta. ¿Cambió la fecha de cierre? Revisá y ajustá si corresponde."},
        ],
    )
```

- [ ] **Step 5: Aplicar y verificar**

Run: `alembic upgrade head && psql -d margin -tAc "select count(*) from review_finding_codes;"`
Expected: `10`.

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models/review_finding_code.py backend/app/models/__init__.py backend/alembic/versions
git commit -m "feat(backend): tabla review_finding_codes con seed"
```

---

## Task 6: Verificación de regresión

**Files:** ninguno.

- [ ] **Step 1: Correr la suite completa (los modelos nuevos no rompen el harness)**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q`
Expected: pasan todos los tests existentes (16). El harness hace `create_all` sobre `margin_test` e incluye las 5 tablas nuevas sin problema.

- [ ] **Step 2: Resumen de conteos en `margin`**

Run:
```bash
psql -d margin -tAc "select 'currencies', count(*) from currencies
  union all select 'currency_rates', count(*) from currency_rates
  union all select 'priority_levels', count(*) from priority_levels
  union all select 'institutions', count(*) from institutions
  union all select 'review_finding_codes', count(*) from review_finding_codes;"
```
Expected: currencies 5, currency_rates 2560, priority_levels 6, institutions 5, review_finding_codes 10.

---

## Notas de cierre

- Al terminar: las 5 tablas maestras existen, migradas y sembradas; las FKs aguas abajo (incomes, obligations, plans, financings, etc.) quedan destrabadas.
- **Cierre:** squash-merge de `feat/master-tables` → un commit `feat: tablas maestras` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** currencies (T1) ✓; currency_rates + seed generado 2026-04→2027-12 (T2) ✓; priority_levels (T3) ✓; institutions (T4) ✓; review_finding_codes (T5) ✓; convención plata=Numeric/Decimal en `currency_rates.value` ✓; ids fijos (autoincrement=False) ✓; sin endpoints/tests nuevos ✓; verificación por psql ✓. Sin FK en review_finding_codes ✓.
- **Placeholders:** ninguno; cada modelo y seed con contenido completo y textos exactos de Notion.
- **Consistencia:** nombres de tabla y columnas idénticos entre modelo, seed (`sa.column`) y verificación psql; orden de migraciones respeta FKs (currencies antes de currency_rates).
