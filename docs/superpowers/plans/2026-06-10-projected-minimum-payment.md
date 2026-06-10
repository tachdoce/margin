# Mínimo proyectado = 15% del amount — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** En el motor de tarjetas, los meses proyectados (Resp 2) guardan `minimum_payment = 15% del amount` (constante compartida) en vez de `null`.

**Architecture:** Constante `PROJECTED_MINIMUM_RATE` en un módulo nuevo `app/services/cash_flow/constants.py` (única fuente, reusable por el motor y el GET). El bloque de proyección de `materialize_credit_card` calcula `amount * 0.15` redondeado a 2 decimales. La Responsabilidad 1 (último resumen) no cambia.

**Tech Stack:** SQLAlchemy 2.0 · Decimal · pytest.

**Spec:** [docs/superpowers/specs/2026-06-10-projected-minimum-payment-design.md](../specs/2026-06-10-projected-minimum-payment-design.md)

**Branch:** ya estás en `feat/projected-minimum-payment` (el spec ya está commiteado ahí). Squash-merge al final. **No tocar Notion.**

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`. Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

**Contexto verificado:** `minimum_payment` es `Numeric(12,2)` nullable. La proyección está en `materialize_credit_card`, bloque "Responsabilidad 2", hoy con `minimum_payment=None`. 3 tests existentes afirman `minimum_payment is None` en proyectadas (se actualizan acá).

---

## File Structure

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow/constants.py` | **nuevo**: `PROJECTED_MINIMUM_RATE` |
| `app/services/cash_flow/credit_cards.py` | Resp 2: `minimum_payment` = 15% del amount (+ imports) |
| `tests/test_cashflow_credit_cards.py` | test del 15% + actualizar 3 asserts viejos de `None` |

---

## Task 1: Mínimo proyectado = 15% del amount

**Files:** `app/services/cash_flow/constants.py`, `app/services/cash_flow/credit_cards.py`, `tests/test_cashflow_credit_cards.py`

- [ ] **Step 1: Test que falla (rojo)** — en `tests/test_cashflow_credit_cards.py`, en `test_pending_installment_projects_remaining_months`, reemplazar la línea `assert junio.minimum_payment is None` por estas dos:

```python
    assert junio.minimum_payment == Decimal("299.63")  # 1997.50 * 0.15 (R2 proyectado, HALF_UP)
    assert keys[(2026, 5, 1)].minimum_payment == Decimal("600.00")  # R1 sigue con el mínimo del banco
```

- [ ] **Step 2: Run → rojo**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py::test_pending_installment_projects_remaining_months -q`
Expected: FALLA en el assert de `junio.minimum_payment` (hoy es `None`, no `299.63`).

- [ ] **Step 3: Crear la constante** `app/services/cash_flow/constants.py`:

```python
from decimal import Decimal

# Mínimo de pago estimado para los meses PROYECTADOS de tarjeta (no hay resumen emitido): 15% del amount.
PROJECTED_MINIMUM_RATE = Decimal("0.15")
```

- [ ] **Step 4: Imports en el motor** — en `app/services/cash_flow/credit_cards.py`, cambiar la línea `from decimal import Decimal` por:

```python
from decimal import ROUND_HALF_UP, Decimal
```

Y agregar, con los demás imports de `app.services.cash_flow`:

```python
from app.services.cash_flow.constants import PROJECTED_MINIMUM_RATE
```

- [ ] **Step 5: Calcular el mínimo en la proyección** — en `materialize_credit_card`, en el target de la Responsabilidad 2, reemplazar `minimum_payment=None,` por:

```python
                minimum_payment=(amount * PROJECTED_MINIMUM_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
```

(La Responsabilidad 1 — el bloque del último resumen, con `minimum_payment=minimum` — queda **igual**.)

- [ ] **Step 6: Run el test del Step 1 → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py::test_pending_installment_projects_remaining_months -q`
Expected: PASS.

- [ ] **Step 7: Actualizar los otros 2 tests que afirmaban `None`.**

En `test_subscription_projects_every_month`, reemplazar `assert sample.minimum_payment is None` por:
```python
    assert sample.minimum_payment == Decimal("10.50")  # 69.99 * 0.15, HALF_UP
```

En `test_projection_becomes_real`, reemplazar `assert proj_may.minimum_payment is None` por:
```python
    assert proj_may.minimum_payment == Decimal("15.00")  # 100.00 * 0.15
```

- [ ] **Step 8: Run el archivo completo → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py -q`
Expected: PASS. (`test_two_currencies` sigue verde: la entry de R1 mantiene `minimum_payment == 600.00`.)

- [ ] **Step 9: Suite completa → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q`
Expected: todo verde.

- [ ] **Step 10: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow/constants.py app/services/cash_flow/credit_cards.py tests/test_cashflow_credit_cards.py && git commit -m "feat: mínimo proyectado de tarjetas = 15% del amount (constante compartida)"
```

---

## Task 2: Cierre

- [ ] **Step 1: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado: **squash-merge** de `feat/projected-minimum-payment` a `main` (1 commit). Push **manual**. (No tocar Notion.)

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** §1 constante (Step 3); §2 Resp 2 = 15% (Steps 4-5), Resp 1 intacta (nota en Step 5);
  §3 sin backfill (no hay paso de datos); §5 tests proyectada 15% + R1 real (Steps 1, 7). ✓
- **Placeholder scan:** sin TBD/TODO; todo el código escrito; valores de los asserts calculados
  (1997.50·0.15=299.63; 69.99·0.15=10.50; 100·0.15=15.00, HALF_UP). ✓
- **Consistencia:** `PROJECTED_MINIMUM_RATE` definida en Step 3, importada en Step 4, usada en Step 5;
  `ROUND_HALF_UP`/`Decimal` importados antes de usarse. ✓
- **Tests viejos:** los 3 asserts de `None` (líneas ~222, ~236, ~277) se actualizan (Steps 1, 7);
  `test_two_currencies` (R1) no cambia. ✓
- **Sin Notion** en el cierre. ✓
```