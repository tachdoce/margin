# Refactor DRY: validadores de obligación + effective_rate — Diseño

> Refactor que **preserva comportamiento**: extrae dos duplicaciones que fuimos arrastrando del subdominio
> Obligaciones. **(A)** los validadores de campos de obligación, duplicados entre `expense_service` y
> `debt_service`; **(B)** la fórmula de tasa efectiva con IVA, duplicada entre los motores `plan_movements`
> y `debts`. No agrega features ni tests nuevos de comportamiento: la suite existente (270) es la red de
> seguridad. **C (reconciliación UPSERT) queda fuera** de este slice (decisión del usuario).

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Tipo:** refactor (preserva comportamiento).
- **Cierre:** rama `feat/refactor-dry-obligaciones`, **squash-merge** a `main`.

---

## 1. Alcance

- **A:** crear `app/services/obligation_common.py` con los validadores compartidos; migrar `expense_service`
  y `debt_service` a usarlos (borrar sus copias privadas).
- **B:** crear `app/services/cash_flow/rates.py` con `effective_rate`; migrar el motor `plan_movements` y el
  motor `debts` (borrar sus copias privadas de `_effective_rate`).

**Fuera de alcance:** C (extraer el reconciliador UPSERT de incomes/expenses/debts) — se evaluará en un slice
aparte. Cualquier cambio de comportamiento.

---

## 2. A — validadores de obligación

Hoy estos 4 helpers son **byte a byte idénticos** en `expense_service` y `debt_service` (privados,
`_validate_*`):

- `validate_priority(db, priority_level)` — None / `== 1` (Ineludible) / inexistente → `priority_level_invalid`.
- `validate_description(description) -> str` — `trim()` `< 8` → `description_invalid`; devuelve el trim.
- `validate_amount(amount)` — None / `<= 0` → `amount_invalid`.
- `validate_due_day(due_day)` — con valor y fuera de 1–31 → `due_day_invalid`.

**Nuevo módulo** `app/services/obligation_common.py`:
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

Pasan de privados a **públicos** (sin guion bajo): son la API del módulo compartido (mismo criterio que
`scoping.require_user_currency`).

**Migración:**
- `expense_service`: borrar las 4 funciones `_validate_*` y las constantes `MIN_DESCRIPTION_LENGTH` /
  `SYSTEM_PRIORITY_LEVEL`; `from app.services.obligation_common import (validate_amount, validate_description,
  validate_due_day, validate_priority)`; reemplazar las llamadas (`_validate_x(...)` → `validate_x(...)`).
- `debt_service`: ídem.

El comportamiento no cambia: mismos error codes, mismo trim devuelto.

---

## 3. B — effective_rate

Hoy `_effective_rate` es **idéntico** en el motor `plan_movements`
([plan_movements.py:32-37](../../../backend/app/services/cash_flow/plan_movements.py#L32-L37)) y en el motor
`debts`.

**Nuevo módulo** `app/services/cash_flow/rates.py`:
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
(`vat_rate` se tipa `Decimal | None`: solo se usa cuando `rate` no es None, así que el caller que no tiene
tasas puede pasar None sin problema — cubre el guard de `debts`.)

**Migración:**
- Motor `plan_movements`: borrar `_effective_rate`; `from app.services.cash_flow.rates import effective_rate`;
  reemplazar las 2 llamadas (`_effective_rate(...)` → `effective_rate(...)`). Quitar el import de
  `ROUND_HALF_UP` si queda sin uso (verificar; `Decimal` probablemente sigue usándose).
- Motor `debts`: ídem.

El comportamiento no cambia: misma fórmula, mismo redondeo.

---

## 4. Decisiones, con su porqué

- **Públicos en los módulos compartidos:** son la interfaz que importan otros módulos (igual que `scoping`).
- **`obligation_common` separado de `scoping`:** `scoping` es "pertenece al país del usuario"; esto son
  validaciones de campos de obligación. Conceptos distintos, módulos distintos.
- **`rates.py` dentro de `cash_flow/`:** la tasa efectiva es un concepto del flujo de caja (la usan los
  motores al materializar), no de los endpoints.
- **C fuera:** el reconciliador es más invasivo (3 motores) y de mayor riesgo; se hace aparte si se decide.
- **Sin tests nuevos de comportamiento:** es refactor; la suite existente (incomes, plan_movements, expenses,
  debts) cubre que el comportamiento no cambió. Se pueden sumar 1-2 tests unitarios mínimos de los módulos
  nuevos (opcional, por prolijidad), pero la garantía real es la regresión verde.

---

## 5. Verificación

- La suite completa (`pytest -q`) sigue **verde** sin tocar tests existentes — es lo que garantiza que el
  refactor no cambió comportamiento.
- Tests unitarios mínimos opcionales: `tests/test_obligation_common.py` (los 4 validadores, casos
  positivo/negativo) y `tests/test_rates.py` (`effective_rate`: con IVA, sin IVA, None). Si se agregan,
  reusan fixtures de conftest.

---

## 6. Plan de implementación (orientativo)

Un slice (`feat/refactor-dry-obligaciones`):
1. **A:** crear `obligation_common.py` → migrar `expense_service` → migrar `debt_service` → suite verde →
   commit.
2. **B:** crear `cash_flow/rates.py` → migrar motor `plan_movements` → migrar motor `debts` → suite verde →
   commit.
3. Suite completa verde → cierre.
