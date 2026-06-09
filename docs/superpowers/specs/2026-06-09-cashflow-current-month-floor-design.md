# CashFlowEngine — materializar desde el primer día del mes actual — Diseño

> Hoy los motores `incomes`/`expenses`/`debts` recortan las entries con `today <= event_date`, así que si el
> día del mes ya pasó, **no se genera la row del mes actual**. Ejemplo: hoy 9 de junio, creo un ingreso
> recurrente día 5 → no aparece junio. El fix: el motor pasa a poseer **del primer día del mes actual en
> adelante**, no "desde hoy".

- **Fecha:** 2026-06-09
- **Estado:** aprobado para implementar
- **Alcance:** backend, 3 motores del `CashFlowEngine`: `incomes`, `expenses`, `debts`.
- **Cierre:** rama `feat/cashflow-current-month-floor`, **squash-merge** a `main`.
- **Fuera de alcance:** `open_debts` (entries sin `event_date`), `plan_movements` y `credit_cards` (lógica de
  fecha propia). El pedido es ingreso/gasto/deuda.

---

## 1. Diagnóstico

En cada motor, `_target_event_dates(source, today, horizon)` arma las fechas objetivo y filtra con
`today <= ed <= horizon` (en las dos ramas: recurrente y única/cuota). Para el mes actual, si `ed` cae antes de
`today`, queda fuera. Además, el borrado de entries stale usa `e.event_date >= today` (solo borra "futuras").

Resultado: el mes actual se omite cuando su día nominal ya pasó.

## 2. Regla nueva

El motor posee **`[primer día del mes actual, horizonte]`** en vez de `[hoy, horizonte]`. Concretamente, en
los 3 motores:

```python
month_start = today.replace(day=1)
```

- **Generación de targets:** `today <= ed <= horizon` → `month_start <= ed <= horizon` (las **2** ocurrencias
  por motor: rama recurrente y rama única/primera cuota).
- **Borrado de stale:** `e.event_date >= today` → `e.event_date >= month_start` (1 ocurrencia por motor). Se
  **mantiene** la protección de pagos reales existente (incomes: `e.id not in paid_ids`; debts: raise si tiene
  pago real; expenses: la guarda actual tal cual, solo cambiando el piso de fecha).

Simetría: la misma cota inferior (`month_start`) gobierna lo que se crea y lo que se limpia. Así, al reproyectar
(editar la fuente), una entry stale del mes actual se limpia igual que las futuras — sin dejar una fila colgada
en el mes actual.

## 3. Efecto y casos borde

- **Recurrente, día < hoy:** se genera la row del mes actual (el caso reportado).
- **Único / primera cuota fechado antes en el mes actual:** se genera (regla única para todos los tipos).
- **Meses enteramente pasados** (`ed < month_start`): siguen excluidos — el motor no modela el pasado.
- **Entry del mes actual con pago real:** protegida del borrado por la guarda de pagos (no cambia).
- **Reconciliación por clave lógica `(year, month, currency)`:** intacta — el mes actual se matchea por mes sin
  importar el día, así que editar el día actualiza la fila (no duplica).

## 4. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow/incomes.py` | `month_start` + 3 reemplazos (2 target, 1 borrado) |
| `app/services/cash_flow/expenses.py` | ídem |
| `app/services/cash_flow/debts.py` | ídem |

Sin cambios de modelo, migración ni endpoints.

## 5. Tests

Cada test pasa `today` explícito a `materialize_*` (las funciones ya lo aceptan) para fijar el día.

- **incomes** (`tests/test_cashflow_incomes.py`): recurrente `payment_day` < `today.day`, mismo mes → existe la
  entry del mes actual; fixed-term con `first_income_date` antes-en-el-mes → existe; mes enteramente pasado →
  no se genera; entry del mes actual con pago real sobrevive a un reproject (editar otra cosa).
- **expenses** (`tests/test_cashflow_expenses.py`): gasto recurrente `due_day` < `today.day` → existe; gasto
  único fechado antes-en-el-mes → existe; pasado → excluido.
- **debts** (`tests/test_cashflow_debts.py`): deuda con `first_due_date` / `due_day` antes-en-el-mes → existe la
  cuota del mes actual; deuda con cuota del mes actual y pago real → sobrevive a reproject.
- Suite completa verde (regresiones: algunos tests existentes asumen el piso "hoy"; ajustar los que se apoyen
  en que el mes actual se omitía).

## 6. Notion

Revisar `Backend → Engines → CashFlowEngine` (y subpáginas incomes/expenses/debts): si documentan el piso como
"desde hoy" / "futuras", actualizar a "desde el primer día del mes actual". Si no lo fijan explícitamente, no
se toca.

## 7. Plan (orientativo)

Un slice (`feat/cashflow-current-month-floor`), TDD por motor: test del mes-actual (rojo) → `month_start` en ese
motor (verde) → repetir para los 3 → suite completa → Notion → cierre.
