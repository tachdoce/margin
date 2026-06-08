# Refactor DRY: validadores + effective_rate — Plan de implementación

> **For agentic workers:** Ejecutar según el modo que elija el usuario (inline o subagente con higiene de
> comandos: `cd` no `git -C`, sin `2>&1`). Refactor que **preserva comportamiento**: la suite existente es la
> red de seguridad. TDD para los módulos nuevos; commit por task.

**Goal:** Eliminar 2 duplicaciones — (A) validadores de obligación (`expense_service`/`debt_service`), (B)
`effective_rate` (motores `plan_movements`/`debts`) — extrayéndolos a módulos compartidos.

**Architecture:** `obligation_common.py` (validadores públicos) + `cash_flow/rates.py` (`effective_rate`).
Los consumidores importan de ahí y borran sus copias. Sin cambios de comportamiento.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, pytest. Spec:
`docs/superpowers/specs/2026-06-08-refactor-dry-obligaciones-design.md`.

**Rama:** `feat/refactor-dry-obligaciones` → squash-merge a `main`.

---

## Task 0: Crear la rama

- [ ] **Step 1:**

```bash
git checkout -b feat/refactor-dry-obligaciones
```

---

## Task 1: A — obligation_common + migrar services

**Files:**
- Create: `backend/app/services/obligation_common.py`
- Modify: `backend/app/services/expense_service.py`
- Modify: `backend/app/services/debt_service.py`
- Test: `backend/tests/test_obligation_common.py`

- [ ] **Step 1: Escribir el test del módulo (rojo)**

`backend/tests/test_obligation_common.py`:

```python
from decimal import Decimal

import pytest

from app.core.errors import AppError, ErrorCode
from app.models.priority_level import PriorityLevel
from app.services.obligation_common import (
    validate_amount,
    validate_description,
    validate_due_day,
    validate_priority,
)


@pytest.fixture
def priorities(db_session):
    db_session.add_all([
        PriorityLevel(level=1, name="Ineludible", description="x"),
        PriorityLevel(level=2, name="Esencial", description="x"),
    ])
    db_session.flush()


def test_validate_priority_ok(db_session, priorities):
    validate_priority(db_session, 2)  # no levanta


def test_validate_priority_sistema(db_session, priorities):
    with pytest.raises(AppError) as e:
        validate_priority(db_session, 1)
    assert e.value.code == ErrorCode.priority_level_invalid


def test_validate_priority_inexistente(db_session, priorities):
    with pytest.raises(AppError):
        validate_priority(db_session, 999)


def test_validate_priority_none(db_session, priorities):
    with pytest.raises(AppError):
        validate_priority(db_session, None)


def test_validate_description_trims():
    assert validate_description("  Alquiler depto  ") == "Alquiler depto"


def test_validate_description_corta():
    with pytest.raises(AppError) as e:
        validate_description("corta")
    assert e.value.code == ErrorCode.description_invalid


def test_validate_amount_ok():
    validate_amount(Decimal("1.00"))


def test_validate_amount_cero():
    with pytest.raises(AppError) as e:
        validate_amount(Decimal("0"))
    assert e.value.code == ErrorCode.amount_invalid


def test_validate_due_day_ok():
    validate_due_day(15)
    validate_due_day(None)


def test_validate_due_day_fuera_de_rango():
    with pytest.raises(AppError) as e:
        validate_due_day(40)
    assert e.value.code == ErrorCode.due_day_invalid
```

- [ ] **Step 2: Correr, verificar que falla**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_obligation_common.py -q
```
Esperado: FAIL (ModuleNotFoundError: app.services.obligation_common).

- [ ] **Step 3: Crear el módulo**

`backend/app/services/obligation_common.py`:

```python
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.priority_level import PriorityLevel

MIN_DESCRIPTION_LENGTH = 8
SYSTEM_PRIORITY_LEVEL = 1  # Ineludible: solo lo asigna el sistema


def validate_priority(db: Session, priority_level: int | None) -> None:
    if (
        priority_level is None
        or priority_level == SYSTEM_PRIORITY_LEVEL
        or db.get(PriorityLevel, priority_level) is None
    ):
        raise AppError(ErrorCode.priority_level_invalid, field="priority_level")


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

- [ ] **Step 4: Correr el test del módulo, verificar verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_obligation_common.py -q
```
Esperado: PASS (10 tests).

- [ ] **Step 5: Migrar `expense_service.py`**

- Borrar las 4 funciones `_validate_priority`, `_validate_description`, `_validate_amount`,
  `_validate_due_day` y las constantes `MIN_DESCRIPTION_LENGTH` / `SYSTEM_PRIORITY_LEVEL`.
- Agregar el import:
  ```python
  from app.services.obligation_common import (
      validate_amount,
      validate_description,
      validate_due_day,
      validate_priority,
  )
  ```
- Reemplazar las llamadas: `_validate_priority(` → `validate_priority(`, `_validate_description(` →
  `validate_description(`, `_validate_amount(` → `validate_amount(`, `_validate_due_day(` →
  `validate_due_day(`.
- **Conservar** `_validate_form` y `_validate_first_due_date_future` (son específicos de expenses) — solo
  asegurarse de que ya no referencien las constantes borradas (no lo hacen).

- [ ] **Step 6: Migrar `debt_service.py`**

- Borrar las mismas 4 funciones y las 2 constantes.
- Agregar el mismo import de `obligation_common`.
- Reemplazar las llamadas igual que arriba.
- **Conservar** `_validate_institution`, `_validate_rate`, `_validate_deuda_form`, `_validate_open_debt_form`
  (específicos de debts).

- [ ] **Step 7: Verificar que no quedan referencias colgadas + suite de los afectados**

```bash
cd /Users/tachone/proyectos/margin/backend && grep -n "_validate_priority\|_validate_description\|_validate_amount\|_validate_due_day" app/services/expense_service.py app/services/debt_service.py
```
Esperado: sin resultados (todas migradas).

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_expenses.py tests/test_debts.py tests/test_obligations.py tests/test_obligation_common.py -q
```
Esperado: PASS (sin cambios de comportamiento).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/obligation_common.py backend/app/services/expense_service.py backend/app/services/debt_service.py backend/tests/test_obligation_common.py
git commit -m "refactor: extraer validadores de obligación a obligation_common

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: B — cash_flow/rates + migrar motores

**Files:**
- Create: `backend/app/services/cash_flow/rates.py`
- Modify: `backend/app/services/cash_flow/plan_movements.py`
- Modify: `backend/app/services/cash_flow/debts.py`
- Test: `backend/tests/test_rates.py`

- [ ] **Step 1: Escribir el test del módulo (rojo)**

`backend/tests/test_rates.py`:

```python
from decimal import Decimal

from app.services.cash_flow.rates import effective_rate


def test_effective_rate_con_vat():
    assert effective_rate(Decimal("55.00"), True, Decimal("22.00")) == Decimal("67.10")


def test_effective_rate_sin_vat():
    assert effective_rate(Decimal("55.00"), False, Decimal("22.00")) == Decimal("55.00")


def test_effective_rate_none():
    assert effective_rate(None, True, Decimal("22.00")) is None
    assert effective_rate(None, True, None) is None
```

- [ ] **Step 2: Correr, verificar que falla**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_rates.py -q
```
Esperado: FAIL.

- [ ] **Step 3: Crear el módulo**

`backend/app/services/cash_flow/rates.py`:

```python
from decimal import ROUND_HALF_UP, Decimal


def effective_rate(rate: Decimal | None, rates_add_vat: bool, vat_rate: Decimal | None) -> Decimal | None:
    """Tasa efectiva con el IVA ya resuelto. NULL → NULL. Si rates_add_vat: rate × (1 + vat_rate/100),
    cuantizada a 2 decimales (ROUND_HALF_UP)."""
    if rate is None:
        return None
    if rates_add_vat:
        rate = rate * (Decimal(1) + vat_rate / Decimal(100))
    return rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

- [ ] **Step 4: Correr el test del módulo, verificar verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_rates.py -q
```
Esperado: PASS (3 tests).

- [ ] **Step 5: Migrar el motor `plan_movements`**

- Borrar la función `_effective_rate`.
- Borrar el import `from decimal import ROUND_HALF_UP, Decimal` (queda sin uso — `Decimal`/`ROUND_HALF_UP`
  solo se usaban ahí; verificar con el grep del Step 7).
- Agregar `from app.services.cash_flow.rates import effective_rate`.
- Reemplazar las 2 llamadas `_effective_rate(` → `effective_rate(`.

- [ ] **Step 6: Migrar el motor `debts`**

- Ídem: borrar `_effective_rate`, borrar `from decimal import ROUND_HALF_UP, Decimal`, agregar el import de
  `effective_rate`, reemplazar las 2 llamadas.

- [ ] **Step 7: Verificar imports/referencias + suite de los afectados**

```bash
cd /Users/tachone/proyectos/margin/backend && grep -n "_effective_rate\|ROUND_HALF_UP\|from decimal" app/services/cash_flow/plan_movements.py app/services/cash_flow/debts.py
```
Esperado: sin `_effective_rate`, sin `ROUND_HALF_UP`, sin `from decimal import ...` (ambos motores quedaron
sin uso de `Decimal`; si algún grep mostrara un uso real de `Decimal` que se me pasó, dejar el import
acotado a `Decimal`).

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_debts.py tests/test_plan_movements.py tests/test_rates.py -q
```
Esperado: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/cash_flow/rates.py backend/app/services/cash_flow/plan_movements.py backend/app/services/cash_flow/debts.py backend/tests/test_rates.py
git commit -m "refactor: extraer effective_rate a cash_flow/rates

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Suite completa

- [ ] **Step 1:**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```
Esperado: PASS (todo verde; +13 tests unitarios nuevos, comportamiento del resto intacto).

---

## Cierre

Tras Task 3 verde: **finishing-a-development-branch** → squash-merge `feat/refactor-dry-obligaciones` a
`main` → push (manual/prompteado).
