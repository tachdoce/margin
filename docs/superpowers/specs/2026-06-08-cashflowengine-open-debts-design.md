# CashFlowEngine.open_debts (motor) — Diseño

> Sub-proyecto #4 del subdominio **Obligaciones**. Materializa `cash_flow_entries` desde las `obligations`
> con `obligation_kind = 'deuda_abierta'` (deudas informales sin cronograma). **Solo el motor**, sin
> endpoints. Es el más simple de la familia: 1 fila atemporal por obligación, sin proyección ni borrado. El
> *qué* está en Notion → Backend → Engines → CashFlowEngine → `open_debts`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tabla `obligations`, `cash_flow_entries`/`cash_flow_payments` (todo en `main`).
- **Cierre:** rama `feat/cashflow-open-debts`, **squash-merge** a `main`.

---

## 1. Alcance

Crear `app/services/cash_flow/open_debts.py` con `materialize_open_debt(db, obligation_id)`, más tests. No
hace commit (lo controla el caller).

**Fuera de alcance:** endpoints, ReviewEngine, otros motores.

---

## 2. Comportamiento

Garantiza **exactamente 1 entry** por obligación deuda_abierta:

1. Relee la `obligations` por id con `SELECT ... FOR UPDATE`. Si no existe → `return`.
2. **Gate:** si `obligation.is_ready` es `False` → **no-op silencioso** (`return`).
3. Busca la entry existente por la **clave lógica** `(source_type='deuda_abierta', source_id)`:
   - Si existe → **UPDATE** `amount = obligation.amount`, `currency_id = obligation.currency_id`.
   - Si no existe → **INSERT** 1 fila.
4. `db.flush()` (sin commit).

La fila lleva: `user_id = obligation.user_id`, `event_date = NULL`, `is_income = False`,
`amount = obligation.amount`, `currency_id = obligation.currency_id`, `source_type = 'deuda_abierta'`,
`source_id = obligation.id`, `financing_rate = NULL`, `overdue_rate = NULL` (una deuda abierta no devenga).

**Firma:** `materialize_open_debt(db, obligation_id)` — **sin** `today`/`horizon` (no hay lógica de fechas).

---

## 3. Diferencias con `expenses`/`debts` (deliberadas)

- **Sin proyección:** 1 fila atemporal (`event_date = NULL`), no N por mes. Sin `compute_event_date`, sin
  horizonte, sin `today`.
- **Sin borrado de stale.** El motor **nunca** borra la entry. Ni con `is_closed = true`: la entry queda
  como histórico de los pagos parciales acumulados (con el `amount` ya ajustado por la acción de cierre que
  la cerró). Por eso no hay path que pueda rozar la regla transversal de "no borrar entries con pago real",
  y los `cash_flow_payments` nunca se tocan.
- **Sin branch de `is_closed`:** el motor siempre hace el UPSERT de la única fila, esté cerrada o no.
- **Clave lógica sin año/mes ni currency:** `(source_type='deuda_abierta', source_id)`. Es única por
  obligación (1 sola fila), así que la búsqueda devuelve 0 o 1.

---

## 4. Decisiones, con su porqué

- **Motor solo, sin endpoints:** mismo enfoque que el resto de la familia; el wiring vive en el slice de
  endpoints (#6).
- **Gate dentro del motor:** contrato de la familia (el endpoint invoca siempre; el motor decide leyendo
  `is_ready`).
- **No se extrae nada compartido:** este motor es trivial y diverge bastante (sin reconciliación por meses);
  la extracción de lo común entre `incomes`/`expenses`/`debts` se evaluará después, aparte.

---

## 5. Tests (`tests/test_cashflow_open_debts.py`)

Sembrando UY + currency + priority_levels + obligation_type de deuda_abierta (`informal`) + usuario + una
`obligations` de deuda_abierta (helper).

- **Materializa 1 fila:** `event_date is None`, `is_income=False`, `source_type='deuda_abierta'`,
  `amount`/`currency_id` de la obligación, `financing_rate`/`overdue_rate` NULL.
- **Idempotente:** dos corridas → sigue **1** entry (no duplica; UPDATE, no segundo INSERT).
- **Editar `amount`:** cambia el `amount` de la obligación + re-materializa → la **misma** entry (mismo id)
  con el `amount` nuevo.
- **Gate `is_ready=False`:** no materializa nada.
- **`is_closed=True`:** la entry **sigue existiendo** (no se borra); su `amount` se actualiza.
- **No toca pagos:** una entry con `cash_flow_payment` (real o planificado) sigue con su pago tras editar el
  `amount` y re-materializar.

---

## 6. Plan de implementación (orientativo)

Un slice (`feat/cashflow-open-debts`), TDD:
1. `tests/test_cashflow_open_debts.py` (rojo) → `app/services/cash_flow/open_debts.py` (verde) → commit.
2. Suite completa verde → cierre.
