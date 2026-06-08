# CashFlowEngine.expenses (motor) — Diseño

> Sub-proyecto #2 del subdominio **Obligaciones**. El motor que materializa `cash_flow_entries` a partir de
> las `obligations` con `obligation_kind = 'gasto'`. **Solo el motor**, sin endpoints (igual que hicimos
> `CashFlowEngine.plan_movements`). Es casi gemelo del motor `incomes` ya existente
> (`app/services/cash_flow/incomes.py`), que se usa como plantilla. El *qué* está en Notion → Backend →
> Engines → CashFlowEngine → `expenses`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tabla `obligations` (#1, en `main`), `cash_flow_entries`/`cash_flow_payments`,
  `compute_event_date` (`app/services/cash_flow/date_utils.py`).
- **Cierre:** rama `feat/cashflow-expenses`, **squash-merge** a `main`.

---

## 1. Alcance

Crear `app/services/cash_flow/expenses.py` con `materialize_expense(db, obligation_id, *, today=None,
horizon=HORIZON)`, más sus tests. El motor (re)materializa las `cash_flow_entries` de una obligación-gasto
por UPSERT contra su clave lógica. No hace commit (lo controla el caller).

**Fuera de alcance:** los endpoints (`POST/PATCH/GET expenses`, DELETE, acknowledge), el `ReviewEngine`, los
motores `debts`/`open_debts`. La extracción de un reconciliador compartido entre motores queda **diferida**
(se hará cuando tengamos debts+open_debts y la forma común sea empírica — decisión tomada en el brainstorming).

---

## 2. Plantilla: el motor `incomes`

`expenses` espeja `materialize_income` ([incomes.py](../../../backend/app/services/cash_flow/incomes.py)):
mismo `HORIZON = date(2027,12,31)`, mismo `_iter_months`, misma estructura de UPSERT + borrado de stale,
misma firma con `today`/`horizon` inyectables, `SELECT ... FOR UPDATE` sobre la fuente, `db.flush()` al
final sin commit. Se copian esos patrones y se adaptan los puntos de §3.

---

## 3. Diferencias respecto a `incomes`

1. **Fuente `Obligation` (no `Income`).** Relee `obligations` por id con `with_for_update()`. `source_type =
   'gasto'`, `is_income = False`. Copia `amount`, `currency_id`, `user_id` de la obligación. Tasas en NULL.
2. **Gate `is_ready` (NUEVO).** Apenas relee la obligación: si `obligation.is_ready` es `False` → **no-op
   silencioso** (`return` sin materializar, sin borrar, sin error). Solo sigue con `is_ready = True`. (El
   motor `incomes` no tiene gate porque ese subdominio no tiene reviewer.)
3. **`is_closed` → objetivo vacío.** En el cálculo de targets, si `obligation.is_closed` es `True`, el
   conjunto objetivo es `[]` (igual que `incomes` hacía con `deleted_at`). El UPSERT entonces borra las
   entries futuras sin pago real de forma natural; no es un caso especial.
4. **Dos formas, con `obligations`:**
   - **Recurrente** (`is_monthly_recurring = True`): 1 fila por mes desde el mes vigente hasta el horizonte,
     fechada `compute_event_date(y, m, due_day, shift_weekends)`. (El endpoint, slice futuro, garantizará
     `due_day` no NULL; el motor confía en eso.)
   - **Único** (`is_monthly_recurring = False`, con `first_due_date`): **1 sola fila** fechada
     `compute_event_date(first_due_date.year, .month, .day, shift_weekends)`. (Difiere de `incomes`, cuyo
     "duración fija" itera `total_months`; un gasto único es **una** fila.)
   - En ambas, solo se incluye el `event_date` si `today <= ed <= horizon`.
5. **Salvaguarda más estricta que `incomes`.** Al borrar stale: una entry futura fuera del objetivo que
   tenga un pago **real** (`plan_id IS NULL`) **no se borra y el motor lanza excepción** (fuerza rollback),
   en vez de saltarla en silencio. Es un invariante que el endpoint previene; el motor no negocia (Notion:
   "lanza excepción y fuerza el rollback"). Las entries pasadas (`event_date < today`) nunca se tocan; los
   pagos planificados (`plan_id` no NULL) se van con la entry por cascade.

## 4. Clave lógica y reconciliación

Idéntica a `incomes` salvo el `source_type`:
- **Clave:** `(source_type='gasto', source_id, año(event_date), mes(event_date), currency_id)`.
- **UPSERT:** por cada `event_date` objetivo, buscar la entry existente por `(año, mes, currency_id)`; si
  está → UPDATE (`amount`, `event_date`); si no → INSERT.
- **Stale:** las existentes cuyo `(año, mes, currency_id)` no está en el objetivo → borrar **solo** las
  futuras (`event_date >= today`) sin pago real; si una futura stale tiene pago real → **raise** (§3.5).

## 5. Decisiones, con su porqué

- **Motor solo, sin endpoints:** mismo enfoque que `plan_movements`; el wiring vive en el slice de endpoints
  (#6), que correrá `ReviewEngine` → `materialize_expense` en la misma transacción.
- **Gate dentro del motor, no en el caller:** contrato de la familia (`CashFlowEngine → Contrato de
  invocación`): el endpoint siempre invoca; el motor decide si materializa leyendo `is_ready`.
- **Confía en el caller para el kind:** la forma (recurrente/único) se deriva de
  `is_monthly_recurring`/`first_due_date`, sin necesitar el `obligation_kind`. El query de existentes filtra
  `source_type='gasto'`, así que aunque se invocara de más, solo toca entries de gasto.
- **`today`/`horizon` inyectables:** tests deterministas (Postgres `now()` es constante dentro de una
  transacción; acá lo pasamos explícito).
- **Espejo de `incomes`, sin extraer todavía:** evita abstracción prematura antes de ver `debts`/`open_debts`.

## 6. Tests (`tests/test_cashflow_expenses.py`)

Sembrando UY + currency + priority_levels + obligation_types + usuario + una `obligations` de gasto (helper).
`today`/`horizon` fijos para determinismo. Consultas directas a `CashFlowEntry`/`CashFlowPayment`.

- **Recurrente** (`is_ready=True`, `due_day`): materializa 1 entry por mes desde `today` hasta `horizon`;
  cada una con `is_income=False`, `source_type='gasto'`, `amount`/`currency_id` de la obligación, tasas NULL.
- **Único** (`first_due_date`, `due_day=None`): materializa **1** entry en esa fecha.
- **Gate:** `is_ready=False` → no materializa nada (y si había entries previas, quedan intactas).
- **`is_closed=True`:** borra las entries futuras sin pago real (objetivo vacío).
- **Cambio recurrente↔único:** reconcilia (borra meses que sobran, crea/actualiza los que faltan) por UPSERT,
  preservando el `id` de las entries que siguen.
- **Pago real:** una entry futura con `cash_flow_payment` (`plan_id IS NULL`) que quedaría stale → el motor
  **lanza excepción** (no la borra). Una con pago **planificado** (`plan_id` no NULL) sí se borra.
- **Pasado intacto:** entries con `event_date < today` no se tocan.
- **`shift_weekends`:** un `due_day` que cae finde se corre (o queda literal) según el flag (apoyado en
  `compute_event_date`, ya testeado aparte — 1 caso de humo).
- **Sin commit:** el motor hace `flush`, no `commit` (el test controla la transacción).

## 7. Plan de implementación (orientativo)

Un slice (`feat/cashflow-expenses`), TDD:
1. `tests/test_cashflow_expenses.py` (rojo) → `app/services/cash_flow/expenses.py` (verde) → commit.
2. Suite completa verde → cierre.
