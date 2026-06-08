# Endpoints de expenses (6a) — Diseño

> Sub-slice **6a** del sub-proyecto #6 (endpoints) del subdominio **Obligaciones**. Los 3 endpoints de
> gastos: `POST /expenses`, `PATCH /expenses/{id}`, `GET /expenses`. Cablean la maquinaria ya construida —
> validación por kind → `ReviewEngine.review_obligation` → `CashFlowEngine.materialize_expense`, todo en una
> transacción. El *qué* está en Notion → Endpoints → Obligaciones → POST/PATCH/GET expenses (+ la sección
> "Estructura común").

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tabla `obligations`, `review_obligation` (#5), `materialize_expense` (#2),
  `scoping.require_user_currency`, maestras `obligation_types`/`priority_levels`/`currencies` (todo en `main`).
- **Cierre:** rama `feat/endpoints-expenses`, **squash-merge** a `main`.

---

## 1. Alcance

- **Router** `app/routers/expenses.py` (finito), registrado en `app/main.py`.
- **Servicio** `app/services/expense_service.py`: `create_expense`, `list_expenses`, `update_expense` + helpers.
- **Schemas** `app/schemas/expense.py`: `ExpenseCreate`, `ExpenseUpdate`, `ExpenseOut`.
- **Error codes nuevos** en `app/core/errors.py`.
- **Amend a `app/services/review/obligations.py`** (#5): agregar el short-circuit `is_closed` a
  `review_obligation` (+ su test). Pequeño, pero necesario para la orquestación uniforme (§4).

**Fuera de alcance:** endpoints de debts (6b), DELETE + acknowledge (6c), vista web.

---

## 2. Schemas

- **`ExpenseCreate`** (POST): `obligation_type_id: int`, `priority_level: int`, `description: str`,
  `is_monthly_recurring: bool`, `due_day: int | None = None`, `first_due_date: date | None = None`,
  `currency_id: int`, `amount: Decimal`, `shift_weekends: bool | None = None`. (`institution_id` **no** está
  en el schema — un gasto no lleva institución.)
- **`ExpenseUpdate`** (PATCH): todos opcionales (semántica vía `model_fields_set`): `obligation_type_id`,
  `priority_level`, `description`, `is_monthly_recurring`, `due_day` (nullable), `first_due_date` (nullable),
  `currency_id`, `amount`, `shift_weekends`, `is_closed`.
- **`ExpenseOut`** (con `from_model`): `id, obligation_type_id, priority_level, description,
  is_monthly_recurring, due_day, first_due_date, currency_id, amount, shift_weekends, is_closed,
  review_findings, is_ready`. **`review_findings` se expone como `list[str]`** (parseado con `json.loads` de
  la columna text). No se exponen `reviewed_at`/`user_acknowledged_at`. Plata como string (convención).

---

## 3. Error codes nuevos (`app/core/errors.py`)

- `expense_type_invalid` (422, "Tipo de gasto no válido.")
- `priority_level_invalid` (422, "Nivel de prioridad no válido.")
- `description_invalid` (422, "La descripción es obligatoria y debe tener al menos 8 caracteres.")
- `due_day_invalid` (422, "El día de vencimiento debe estar entre 1 y 31.")
- `one_time_expense_inconsistent` (422, "Un gasto con fecha única debe ser no recurrente y sin día de vencimiento.")
- `expense_recurring_requires_due_day` (422, "Un gasto recurrente necesita un día de vencimiento.")
- `one_time_date_in_past` (422, "La fecha del gasto no puede ser anterior a hoy.")

(`amount_invalid`, `currency_not_available`, `not_found` ya existen.)

---

## 4. Orquestación común (POST y PATCH, 1 transacción)

```
validar → insert/update en obligations → flush
        → ReviewEngine.review_obligation(db, id)         (maneja internamente el caso is_closed)
        → CashFlowEngine.materialize_expense(db, id)     (siempre; el motor decide por is_ready)
        → commit → refresh → ExpenseOut
```
Orquestación **uniforme**: el endpoint **siempre** llama al reviewer y siempre al motor, sin branchear en
`is_closed` ni evaluar `is_ready`. Si el reviewer o el motor lanzan excepción → rollback total.
`MIN_DESCRIPTION_LENGTH = 8`. `user_id` siempre del token.

**Cierre = resolución (lo dueña el reviewer).** `review_obligation` hace **short-circuit** cuando
`obligation.is_closed` es `true`: setea `review_findings = '[]'` e `is_ready = true` (y `reviewed_at = now`)
**sin correr las reglas**. Esto realiza "una obligación cerrada no admite findings" y deja el gate en `true`
para que el motor **sí limpie las entries futuras** (objetivo vacío). Si quedara `is_ready = false` por
findings previos, el motor haría no-op y las futuras quedarían colgando — el bug que esto evita. La
responsabilidad de derivar `is_ready` del estado de la fila vive **solo en el reviewer**; el endpoint no
replica la regla "cerrada ⇒ ready". (Esto suma un amend chico a `review_obligation` —#5— + su test, incluido
en este slice. En gastos los findings nunca ocurren —no hay tasas—, pero la orquestación y el reviewer son
los mismos que en debts, donde sí importa.)

---

## 5. `POST /expenses` → 201

**Validaciones (en orden):**
1. `obligation_type_id` existe y su `obligation_kind == 'gasto'` → si no, `expense_type_invalid`.
2. `currency_id` válido y del país (`require_user_currency`) → `currency_not_available`.
3. `priority_level` existe en `priority_levels` y **≠ 1** (Ineludible, del sistema) → `priority_level_invalid`.
4. `description.strip()` longitud ≥ 8 → `description_invalid`.
5. `amount > 0` → `amount_invalid`.
6. Si `due_day` con valor: 1 ≤ due_day ≤ 31 → `due_day_invalid`.
7. Forma según `is_monthly_recurring`:
   - `true` (recurrente): `due_day` con valor (si falta → `expense_recurring_requires_due_day`) **y**
     `first_due_date` NULL (si viene → `one_time_expense_inconsistent`).
   - `false` (único): `first_due_date` con valor **y** `due_day` NULL (si no → `one_time_expense_inconsistent`).
8. Si `first_due_date` con valor: `>= today` → si no, `one_time_date_in_past`.

**Insert:** campos del body; `shift_weekends = body.shift_weekends or False`; `total_installments`,
`financing_rate`, `overdue_rate`, `origin_obligation_id`, `institution_id` = NULL; `rates_add_vat = True`;
`is_closed = False`; `reviewed_at = NULL`; `review_findings = '[]'`; `user_acknowledged_at = NULL`;
`is_ready = False`. Luego orquestación §4 (reviewer corre siempre en POST).

---

## 6. `GET /expenses` → 200

Solo lectura. `SELECT` de `obligations` JOIN `obligation_types` WHERE `user_id` = token AND
`obligation_kind = 'gasto'`, ORDER BY `created_at DESC`. Incluye los `is_closed = true`. Devuelve
`{"expenses": [ExpenseOut, ...]}` (puede ser `[]`).

---

## 7. `PATCH /expenses/{id}` → 200

**Validaciones:**
1. Obligación con `id` y `user_id` = token; JOIN a tipo: si no existe / no es del usuario / no es kind
   `gasto` → `not_found` (404).
2. PATCH vacío: permitido (no es error; re-corre reviewer + motor sin cambios).
3. Por campo presente (si viene): tipo kind `gasto` (`expense_type_invalid`); `currency_id` del país
   (`currency_not_available`); `priority_level` ≠ 1 y existe (`priority_level_invalid`); `description` ≥ 8
   (`description_invalid`, no acepta `null`); `amount > 0` (`amount_invalid`, no `null`);
   `is_monthly_recurring` bool (no `null`); `due_day` 1–31 si con valor (`due_day_invalid`); `is_closed` bool;
   `shift_weekends` bool (no `null`). `due_day`/`first_due_date` aceptan `null`.
4. **Consistencia post-merge** (estado final, mismo eje que POST §7): recurrente → `due_day` con valor +
   `first_due_date` NULL; único → `first_due_date` con valor + `due_day` NULL. `first_due_date >= today`
   **solo si difiere del guardado** (`one_time_date_in_past`).

**Update:** solo columnas presentes; `user_id`/`id`/`created_at`/`origin_obligation_id`/cuotas/tasas no se
tocan; `updated_at` natural. **Ciclo:** el endpoint siempre llama a `review_obligation` (uniforme); el
reviewer decide según el estado final — si `is_closed = false` corre las reglas (popula
`review_findings`/`is_ready`, resetea `user_acknowledged_at` si hay findings); si `is_closed = true` hace
short-circuit (`review_findings='[]'`, `is_ready=true`, sin reglas). **Motor:** siempre
(`materialize_expense`). Orquestación §4.

---

## 8. Decisiones, con su porqué

- **Router/servicio dedicados:** las validaciones por kind son sustanciales; un módulo propio mantiene el
  foco (mismo criterio que `plan_movements`).
- **`review_findings` como array en el Out:** la columna es text JSON; el contrato expone un array. Se
  parsea en `from_model`.
- **Cierre = resolución, lo dueña el reviewer:** `review_obligation` hace short-circuit si `is_closed`
  (`review_findings='[]'`, `is_ready=true`, sin reglas). Decisión de diseño (vs. setearlo en el endpoint):
  `is_ready` es propiedad del ciclo de revisión, así que su derivación a partir del estado de la fila vive en
  un solo lugar (el reviewer); el endpoint queda uniforme y cualquier ruta que cierre la obligación (PATCH
  hoy, la acción de cierre+creación de deuda_abierta mañana) obtiene el estado correcto sin duplicar la
  regla. Dejar el gate en `true` es lo que permite al motor limpiar las futuras; si quedara `false` por
  findings previos, el motor haría no-op y quedarían huérfanas. Se revisa de nuevo si se reabre.
- **PATCH vacío permitido:** el spec no define `empty_patch` para expenses; un patch vacío es un no-op que
  re-corre reviewer/motor (decisión confirmada en el brainstorming).
- **`user_id` del token; `institution_id` ignorado:** seguridad e invariante de gasto sin institución.
- **`priority_level ≠ 1`:** el nivel Ineludible lo asigna solo el sistema, no la UI.

---

## 9. Tests (`tests/test_expenses.py`)

Helper `_auth` (registra/loguea y devuelve headers) y siembra `obligation_types` (gasto + uno deuda para el
caso de kind inválido), `priority_levels` (incluido el nivel 1) y currency. Consultas directas a
`CashFlowEntry` donde haga falta.

- **POST:** crea recurrente (201, fila + materializa entries de gasto) y único (1 entry); `obligation_type_id`
  de kind deuda → `expense_type_invalid`; moneda de otro país → `currency_not_available`; `priority_level=1`
  → `priority_level_invalid`; `description` corta → `description_invalid`; `amount<=0` → `amount_invalid`;
  `due_day` fuera de 1–31 → `due_day_invalid`; recurrente sin `due_day` → `expense_recurring_requires_due_day`;
  recurrente con `first_due_date` → `one_time_expense_inconsistent`; único sin `first_due_date` →
  `one_time_expense_inconsistent`; `first_due_date` pasada → `one_time_date_in_past`; sin token → 401.
- **GET:** lista solo gastos del usuario, ordenada por `created_at desc`, incluye cerrados; `[]` si no hay;
  no devuelve deudas de otro kind; 401 sin token.
- **PATCH:** cambia `amount` (re-materializa); `is_closed=true` (reviewer no corre; `review_findings=[]` e
  `is_ready=true` en el response; el motor limpia las entries futuras); convertir recurrente→único; estado
  final inconsistente → 422; `{id}` de otro usuario/kind → 404; patch vacío → 200 sin cambios.

> El test del cierre que **limpia futuras estando con findings previos** vive naturalmente en 6b (debts),
> donde los findings sí pueden ocurrir; acá se verifica el estado terminal del cierre (`[]` + `is_ready`).

- **Reviewer (`tests/test_review_obligations.py`, amend):** `review_obligation` sobre una obligación
  `is_closed=true` con tasas que normalmente dispararían findings → short-circuit: `review_findings='[]'`,
  `is_ready=true`, sin importar las reglas. (Este test acompaña el amend del reviewer.)

Regresión `pytest -q` verde.

---

## 10. Plan de implementación (orientativo)

Un slice (`feat/endpoints-expenses`), 4 tasks: (1) amend del reviewer (short-circuit `is_closed` en
`review_obligation` + test), (2) schemas + error codes + `POST` + `GET` (+ router registrado), (3) `PATCH`,
(4) suite completa. TDD por task.
