# Slice 1 — Eliminar `priority_levels` — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar por completo el concepto `priority_levels` del backend (tabla, FKs, modelo, validaciones, schemas, bootstrap y el tipo `adelanto_sueldo`), sin agregar todavía los campos nuevos (eso es el Slice 2).

**Architecture:** Remoción transversal. Como `priority_levels` no lo usa ningún motor (planning/timeline lo ignoran), sacarlo no cambia comportamiento de negocio — solo desaparece de la API (create/update de deudas y gastos ya no piden `priority_level`; bootstrap ya no expone `priority_levels`). Los tests usan `create_all` desde los modelos (no migraciones), así que la migración Alembic solo afecta la base de dev.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, pytest.

**Spec:** `docs/superpowers/specs/2026-06-14-priority-rework-design.md`

**Contexto base:**
- `cd backend && source .venv/bin/activate`; tests `pytest -q`. Suite completa ~2 min.
- Las Tasks 1–3 (producción) dejan la suite **roja** a propósito (los tests todavía referencian `priority`); la Task 4 actualiza los tests y la suite vuelve a **verde**.
- Convención de cierre: NO se hace squash-merge/push automático — se deja la rama para revisión del usuario.

---

### Task 1: Modelos

**Files:**
- Modify: `app/models/obligation.py`
- Modify: `app/models/obligation_type.py`
- Delete: `app/models/priority_level.py`
- Modify: `app/models/__init__.py`

- [ ] **Step 1: Quitar `priority_level` de `Obligation`**

En `app/models/obligation.py`, borrar el bloque (líneas 22–24):
```python
    priority_level: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("priority_levels.level"), nullable=False
    )
```
(`ForeignKey` y `SmallInteger` siguen usándose en otras columnas — no tocar el import.)

- [ ] **Step 2: Quitar `default_priority_level` de `ObligationType`**

En `app/models/obligation_type.py`, borrar el bloque (líneas 18–20):
```python
    default_priority_level: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("priority_levels.level"), nullable=False
    )
```
Era la única columna con FK, así que sacar `ForeignKey` del import (línea 1):
```python
from sqlalchemy import Boolean, Enum, ForeignKey, SmallInteger, String, UniqueConstraint
```
queda:
```python
from sqlalchemy import Boolean, Enum, SmallInteger, String, UniqueConstraint
```

- [ ] **Step 3: Borrar el modelo y su registro**

Borrar el archivo `app/models/priority_level.py`.
En `app/models/__init__.py`, borrar la línea:
```python
from app.models.priority_level import PriorityLevel  # noqa: F401
```

- [ ] **Step 4: Verificar que importa**

Run: `python -c "import app.main"`
Expected: sin error (la app importa sin el modelo).

- [ ] **Step 5: Commit**

```bash
git add app/models/obligation.py app/models/obligation_type.py app/models/priority_level.py app/models/__init__.py
git commit -m "refactor: quitar priority_level/default_priority_level de los modelos"
```

---

### Task 2: Schemas

**Files:**
- Modify: `app/schemas/debt.py`
- Modify: `app/schemas/expense.py`
- Modify: `app/schemas/bootstrap.py`

- [ ] **Step 1: `debt.py` — quitar `priority_level` (4 lugares)**

Borrar `priority_level: int` de `DebtCreate` (línea 13), `priority_level: int | None = None` de `DebtUpdate` (línea 29), `priority_level: int` de `DebtOut` (línea 47), y `priority_level=o.priority_level,` de `from_model` (línea 70).

- [ ] **Step 2: `expense.py` — quitar `priority_level` (4 lugares)**

Borrar `priority_level: int` de `ExpenseCreate` (línea 13), `priority_level: int | None = None` de `ExpenseUpdate` (línea 25), `priority_level: int` de `ExpenseOut` (línea 39), y `priority_level=o.priority_level,` de `from_model` (línea 56).

- [ ] **Step 3: `bootstrap.py` — quitar el catálogo y el default**

Borrar `default_priority_level: int` de `ObligationTypeOut` (línea 23).
Borrar la clase `PriorityLevelOut` entera (líneas 32–35):
```python
class PriorityLevelOut(_Read):
    level: int
    name: str
    description: str
```
Borrar de `Catalogs` la línea (72):
```python
    priority_levels: list[PriorityLevelOut]
```

- [ ] **Step 4: Verificar que importa**

Run: `python -c "import app.main"`
Expected: sin error.

- [ ] **Step 5: Commit**

```bash
git add app/schemas/debt.py app/schemas/expense.py app/schemas/bootstrap.py
git commit -m "refactor: quitar priority_level de schemas de deuda/gasto/bootstrap"
```

---

### Task 3: Servicios + error code

**Files:**
- Modify: `app/services/obligation_common.py`
- Modify: `app/services/debt_service.py`
- Modify: `app/services/expense_service.py`
- Modify: `app/services/bootstrap_service.py`
- Modify: `app/core/errors.py`

- [ ] **Step 1: `obligation_common.py` — borrar `validate_priority`**

Borrar la función `validate_priority` (líneas 10–16), la constante `SYSTEM_PRIORITY_LEVEL` (línea 7), el import `from app.models.priority_level import PriorityLevel` (línea 4) y el import `from sqlalchemy.orm import Session` (línea 1, ya no se usa). El archivo queda:
```python
from app.core.errors import AppError, ErrorCode

MIN_DESCRIPTION_LENGTH = 3


def validate_description(description: str | None) -> str:
    cleaned = (description or "").strip()
    if len(cleaned) < MIN_DESCRIPTION_LENGTH:
        raise AppError(ErrorCode.description_invalid, field="description")
    return cleaned


def validate_amount(amount) -> None:
    if amount is None or amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")


def validate_due_day(due_day: int | None) -> None:
    if due_day is not None and not (1 <= due_day <= 31):
        raise AppError(ErrorCode.due_day_invalid, field="due_day")
```

- [ ] **Step 2: `debt_service.py` — quitar usos**

Quitar `validate_priority,` del bloque de import `from app.services.obligation_common import (...)`.
Borrar la línea `validate_priority(db, payload.priority_level)` del create (línea 98).
Borrar las dos líneas `priority_level=payload.priority_level,` de las dos construcciones de `Obligation(...)` (líneas 112 y 140).
En `update_debt`, borrar el bloque (líneas 189–190):
```python
    if "priority_level" in fields:
        validate_priority(db, payload.priority_level)
```

- [ ] **Step 3: `expense_service.py` — quitar usos**

Quitar `validate_priority,` del import `from app.services.obligation_common import (...)`.
Borrar `validate_priority(db, payload.priority_level)` del create (línea 56).
Borrar `priority_level=payload.priority_level,` de la construcción de `Obligation(...)` (línea 66).
Borrar el bloque del update (líneas 114–115):
```python
    if "priority_level" in fields:
        validate_priority(db, payload.priority_level)
```

- [ ] **Step 4: `bootstrap_service.py` — quitar el catálogo**

Borrar el import `from app.models.priority_level import PriorityLevel` (línea 10).
Borrar la entrada del dict (líneas 28–30):
```python
        "priority_levels": list(
            db.execute(select(PriorityLevel).order_by(PriorityLevel.level)).scalars()
        ),
```

- [ ] **Step 5: `errors.py` — quitar el error code**

Borrar la línea (37):
```python
    priority_level_invalid = (422, "Nivel de prioridad no válido.")
```

- [ ] **Step 6: Verificar que importa**

Run: `python -c "import app.main"`
Expected: sin error.

- [ ] **Step 7: Commit**

```bash
git add app/services/obligation_common.py app/services/debt_service.py app/services/expense_service.py app/services/bootstrap_service.py app/core/errors.py
git commit -m "refactor: quitar validate_priority y el catálogo priority_levels de los servicios"
```

---

### Task 4: Tests (barrido) + borrar los tests de prioridad

Hay 13 archivos de test que referencian prioridad. El cambio es mecánico. Aplicar estas **reglas** a cada archivo donde aparezca, y además **borrar** los tests que probaban específicamente la prioridad.

**Reglas de transformación** (en todos los archivos de la lista):
- (a) Borrar el import `from app.models.priority_level import PriorityLevel` (incluido el import inline dentro de una función en `test_get_cash_flow_entries.py:180`).
- (b) Borrar toda siembra de `PriorityLevel(...)` (líneas `db_session.add(...)`, `.merge(...)`, o entradas dentro de `add_all([...])`). Si está dentro de un `add_all` junto a otros modelos, sacar solo las entradas `PriorityLevel(...)`.
- (c) Borrar el kwarg `default_priority_level=N,` de toda construcción `ObligationType(...)`.
- (d) Borrar el kwarg `priority_level=N,` de toda construcción `Obligation(...)`.
- (e) Borrar `"priority_level": N,` de los dicts de body JSON y `priority_level=N` de los builders/helpers que arman esos dicts (ej. `_cronograma`, `_sin_cronograma`, `_recurrente`, `_unico` en debts/expenses/obligations).

Ejemplo (a/d):
```python
# antes
from app.models.priority_level import PriorityLevel
...
o = Obligation(user_id=user.id, obligation_type_id=1, priority_level=2, description="Luz", ...)
# después
o = Obligation(user_id=user.id, obligation_type_id=1, description="Luz", ...)
```

**Archivos a barrer** (con las reglas de arriba):
`tests/test_obligations.py`, `tests/test_obligations_model.py`, `tests/test_cashflow_open_debts.py`, `tests/test_cashflow_debts.py`, `tests/test_cashflow_expenses.py`, `tests/test_cash_flow_entries_by_source.py`, `tests/test_patch_cash_flow_entry.py`, `tests/test_get_cash_flow_entries.py`, `tests/test_review_obligations.py`, `tests/test_debts.py`, `tests/test_expenses.py`, `tests/test_bootstrap.py`, `tests/test_obligation_common.py`.

**Tests/fixtures a BORRAR enteros** (ya no aplican):
- `tests/test_obligation_common.py`: el import `validate_priority`, la fixture `priorities`, y los tests `test_validate_priority_ok`, `test_validate_priority_sistema`, `test_validate_priority_inexistente`, `test_validate_priority_none`.
- `tests/test_debts.py`: el test que postea `priority_level=1` y espera `"priority_level_invalid"` (≈ líneas 150–153).
- `tests/test_expenses.py`: el test que postea `priority_level=1` y espera `"priority_level_invalid"` (≈ líneas 93–96).
- `tests/test_bootstrap.py`: sacar `"priority_levels"` de la lista de claves esperadas (línea 15), y borrar el bloque que asume el catálogo `priority_levels` (líneas 77–78: `levels = {p["level"] ...}` y su assert).

- [ ] **Step 1: Aplicar el barrido y las eliminaciones** (reglas + listas de arriba).

- [ ] **Step 2: Correr la suite y barrer stragglers**

Run: `pytest -q`
Expected: PASS. Si algo falla por `priority`, aplicar la regla correspondiente al lugar que reste (`grep -rn priority tests/` debe quedar vacío salvo comentarios).

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: quitar priority_levels de los tests y borrar los tests de prioridad"
```

---

### Task 5: Migración Alembic (base de dev)

Los tests no usan migraciones; esto alinea la base de dev `margin` con los modelos.

**Files:**
- Create: `alembic/versions/<rev>_remove_priority_levels.py`

- [ ] **Step 1: Generar la revisión**

Run: `alembic revision -m "remove priority_levels"`
Esto crea el archivo con `revision`/`down_revision` (debe quedar `down_revision = "1a59f3159ebb"`, el head actual; verificar).

- [ ] **Step 2: Escribir `upgrade`/`downgrade`**

Reemplazar el cuerpo por:
```python
def upgrade() -> None:
    op.execute("DELETE FROM obligation_types WHERE code = 'adelanto_sueldo'")
    # En Postgres, DROP COLUMN elimina sola la FK de esa columna.
    op.drop_column("obligations", "priority_level")
    op.drop_column("obligation_types", "default_priority_level")
    op.drop_table("priority_levels")


def downgrade() -> None:
    # best-effort: recrea la tabla y las columnas (sin restaurar FK/NOT NULL ni el seed)
    op.create_table(
        "priority_levels",
        sa.Column("level", sa.SmallInteger(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
    )
    op.add_column("obligation_types", sa.Column("default_priority_level", sa.SmallInteger(), nullable=True))
    op.add_column("obligations", sa.Column("priority_level", sa.SmallInteger(), nullable=True))
```
(Asegurar `import sqlalchemy as sa` arriba — viene en el template de Alembic.)

- [ ] **Step 3: Aplicar a la base de dev**

Run: `alembic upgrade head`
Expected: OK, sin error.

- [ ] **Step 4: Verificar cadena lineal**

Run: `alembic heads`
Expected: un solo head (la nueva revisión).

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat: migración que elimina priority_levels y el tipo adelanto_sueldo"
```

---

### Task 6: Cierre

- [ ] **Step 1: Suite completa verde**

Run: `pytest -q`
Expected: PASS (toda la suite). `grep -rn "priority_level\|priority_levels\|PriorityLevel" app/ tests/` no debe devolver nada (salvo, si quedara, en comentarios).

- [ ] **Step 2: Dejar la rama para revisión**

NO hacer squash-merge ni push a main (el usuario controla qué entra a main). Reportar que el Slice 1 está completo en la rama `feat/priority-rework` y esperar su decisión de merge. El Slice 2 (agregar los campos nuevos) va en su propio plan.
