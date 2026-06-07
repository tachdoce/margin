# `CashFlowEngine.plan_movements` (motor de materialización) — Diseño

> Motor del subdominio **plan_movements** de la familia `CashFlowEngine`: materializa `cash_flow_entries` a
> partir de las filas de `plan_movements` (los movimientos hipotéticos de un plan). Este spec cubre **solo el
> motor**, sin cablearlo a endpoints (los endpoints de `plan_movements` todavía no existen — son un slice
> posterior). Análogo al motor de incomes. El *qué* vive en Notion → Backend → Engines → CashFlowEngine →
> plan_movements, y BD → Flujo de dinero → plan_movements / cash_flow_entries.

- **Fecha:** 2026-06-07
- **Estado:** aprobado para implementar
- **Depende de:** `plan_movements`, `plans`, `cash_flow_entries`, `cash_flow_payments`, `currencies`, `users`,
  `countries` (todos en `main`), y `compute_event_date` (ya existe en `app/services/cash_flow/date_utils.py`).
- **Cierre:** rama `feat/cashflow-engine-plan-movements`, **squash-merge** a `main`.

---

## 1. Alcance

Una pieza nueva: `app/services/cash_flow/plan_movements.py` con `materialize_plan_movement(...)`, que reusa
`compute_event_date`. Sin endpoints, sin validación, sin borrado orquestado.

**División de responsabilidades (confirmada con los endpoints de Notion):** el motor es **pura
materialización**. Toda la validación (consistencia `kind`↔columnas, `currency`, montos, forzar
`income_duration_months=1` en préstamo, "el default no admite movimientos") vive en los **endpoints** (slice
futuro), no en el motor: el motor recibe una fila ya válida y consistente y confía en ella. El **DELETE no
invoca al motor** (el endpoint orquesta el borrado con SQL directo), así que el motor **no tiene rama de
borrado de fuente**: lo único que borra es durante una re-materialización normal (reconciliación cuando el
movimiento se achica).

**Fuera de alcance:** los endpoints `POST/GET/PATCH/DELETE /plans/{id}/movements`, los demás motores de la
familia, y el `PlanEngine`.

---

## 2. Firma y contexto

**Ubicación:** `app/services/cash_flow/plan_movements.py`.

**Firma:** `materialize_plan_movement(db: Session, movement_id: uuid.UUID, *, today: date | None = None,
horizon: date = date(2027, 12, 31)) -> None`

- `today` se resuelve a `date.today()` si no se pasa. `today`/`horizon` inyectables para tests deterministas
  (mismo criterio que el motor de incomes).
- Lee el `plan_movements` con lock: `select(PlanMovement).where(id == movement_id).with_for_update()`. Si no
  existe → `return` (no-op defensivo).
- **`user_id` de las entries:** sube `plan_movements.plan_id → plans.user_id` (la tabla `plan_movements` no
  tiene `user_id` propio). Nunca por parámetro ni del request.
- **No hace `commit`** — la transacción la controla el caller. Si lanza excepción, el caller hace rollback.
- El motor **confía en la fila**: asume que las columnas son consistentes con el `kind` (lo garantiza el
  endpoint). No revalida.

---

## 3. Conjunto objetivo por `kind`

Todas las filas objetivo llevan `source_id = movement.id`, `currency_id = movement.currency_id`,
`user_id = plan.user_id`. El resto depende del `kind`. **No se modela el pasado:** una fila se incluye solo si
su `event_date` (ya fechado) es `>= today` (y `<= horizon`).

### `ingreso` — `is_income=True`, `source_type='plan_movimiento'`, `amount=principal_amount`, tasas NULL
- **única** (`income_duration_months == 1`): 1 fila con `event_date = start_date` (literal exacto, sin ajuste).
- **limitada** (`income_duration_months > 1`): N filas mensuales desde `start_date`,
  `event_date = compute_event_date(año, mes, start_date.day, shift_weekends=False)` (clamp de fin de mes, sin
  corrimiento de finde).
- **recurrente** (`income_duration_months IS NULL`): 1 fila por mes desde `start_date` hasta `horizon`, mismo
  fechado.

### `deuda_informal` — `is_income=False`, `source_type='plan_movimiento'`, tasas NULL
- 1 sola fila con `event_date = start_date` (literal exacto), `amount = principal_amount`.

### `prestamo` — dos clases de filas
- **Entrada de plata** (1 fila): `is_income=True`, `source_type='plan_movimiento_entrada'`,
  `event_date = start_date` (literal exacto), `amount = principal_amount`, tasas NULL.
- **Cuotas** (`total_installments` filas): `is_income=False`, `source_type='plan_movimiento'`, desde
  `installment_start_date`, `event_date = compute_event_date(año, mes, installment_start_date.day,
  shift_weekends=True)` (clamp **+ corrimiento de finde**: la cuota es un vencimiento real), cuota N = mes de
  `installment_start_date` + (N−1) meses. `amount = installment_amount`. `financing_rate`/`overdue_rate` =
  **tasa efectiva** (ver §4).

> **Convivencia entrada + 1ª cuota el mismo mes:** si `start_date` e `installment_start_date` caen en el mismo
> mes, el motor genera 2 filas ese mes apuntando al mismo movimiento — una `plan_movimiento_entrada`
> (`is_income=true`) y una `plan_movimiento` (`is_income=false`). No colisionan porque la clave lógica incluye
> `source_type` (ver §5).

---

## 4. Tasa efectiva (solo `prestamo`, solo las cuotas)

Para cada tasa (`financing_rate`, `overdue_rate`) de la fuente:
- Si es `NULL` → la entry la lleva `NULL`.
- Si tiene valor:
  - `rates_add_vat == True` → `efectiva = rate × (1 + vat_rate/100)`
  - `rates_add_vat == False` → `efectiva = rate`
- Se cuantiza a 2 decimales (la columna es `numeric(5,2)`).

`vat_rate` sale de `countries.vat_rate` del país del usuario (movement → plan → user → `country_code` →
`Country.vat_rate`). Se carga solo en el camino `prestamo` (los demás kinds no devengan).

---

## 5. Reconciliación por UPSERT

**Clave lógica de la entry de plan:** `(source_type, año(event_date), mes(event_date), currency_id)` —
incluye `source_type` (a diferencia de incomes), para que la entrada (`plan_movimiento_entrada`) y la primera
cuota (`plan_movimiento`) convivan el mismo mes sin colisión. `source_id` es fijo (el movimiento).

1. Cargar las entries existentes del movimiento: `source_id = movement.id` con `source_type IN
   ('plan_movimiento', 'plan_movimiento_entrada')`. Indexar por clave lógica.
2. Por cada fila objetivo: si la clave **existe** → **UPDATE** (`amount`, `event_date`, `financing_rate`,
   `overdue_rate`); si **no** → **INSERT**.
3. Las existentes **fuera** del objetivo se borran **si** son futuras (`event_date >= today`). Las entries de
   plan **no reciben pagos reales** (solo planificados del propio plan, que caen por `ON DELETE CASCADE`), así
   que no hay historia financiera real que proteger; no se chequea pago real (a diferencia de incomes). Las
   pasadas se dejan (el motor no modela el pasado).

La unicidad de la clave la garantiza el motor corriendo secuencial bajo el lock `FOR UPDATE` del movimiento;
sin UNIQUE en BD.

---

## 6. Decisiones, con su porqué

- **Motor puro, sin validación:** la validación vive en el endpoint (confirmado en Notion → POST/PATCH). El
  motor confía en la fila y se mantiene chico y enfocado.
- **Sin rama de borrado de fuente:** el DELETE endpoint orquesta el borrado directo; el motor solo borra
  durante la reconciliación normal. No replica esa lógica.
- **Clave lógica con `source_type`:** es lo que permite entrada + 1ª cuota el mismo mes. Es la diferencia
  estructural con la clave de incomes.
- **Fechado distinto por tipo de fila:** ingresos/eventos únicos no corren por finde (es una entrada de plata);
  las cuotas sí (vencimiento real). Lo resuelve el flag `shift_weekends` que el motor pasa a
  `compute_event_date` (`False` para ingreso/entrada, `True` para cuotas) — el `plan_movements` no tiene
  columna `shift_weekends` propia, el criterio es por tipo de fila (Notion).
- **Tasa efectiva congelada al materializar:** la entry guarda la tasa con IVA ya resuelto; si la fuente
  cambia, la re-materialización las reescribe.
- **`today`/`horizon` inyectables y sin commit:** mismos criterios que el motor de incomes.

---

## 7. Tests

`tests/test_cashflow_engine_plan_movements.py` (motor directo, `today`/`horizon` fijos; sembrando country UY +
currency + user + plan + plan_movement):

- **ingreso único** (`income_duration_months=1`): 1 entry en `start_date`, `is_income=True`,
  `source_type='plan_movimiento'`, tasas NULL.
- **ingreso limitado** (`=3`): 3 entries mensuales desde `start_date`.
- **ingreso recurrente** (`NULL`): 1 entry/mes desde `start_date` hasta `horizon`.
- **deuda_informal:** 1 entry en `start_date`, `is_income=False`.
- **prestamo:** 1 entry de entrada (`plan_movimiento_entrada`, `is_income=True`) + N cuotas
  (`plan_movimiento`, `is_income=False`, `amount=installment_amount`).
- **convivencia:** `start_date` e `installment_start_date` el mismo mes → 2 entries ese mes, distinto
  `source_type`, sin colisión.
- **tasa efectiva:** `rates_add_vat=True` con `vat_rate=22` → cuota lleva `rate × 1.22` cuantizado;
  `rates_add_vat=False` → tasa literal; tasa NULL en la fuente → NULL en la entry.
- **cuota corre por finde, ingreso no:** una cuota cuyo día cae sábado se mueve a día hábil; un ingreso cuyo
  día cae sábado queda literal.
- **no modela el pasado:** cuotas/meses con `event_date < today` no se materializan; evento único pasado → 0
  entries.
- **idempotencia:** correr 2× deja el mismo conjunto.
- **reconciliación:** achicar `total_installments` borra las cuotas futuras que sobran; agrandarlo crea las
  nuevas; cambiar `installment_amount` actualiza in place.

Regresión `pytest -q` verde.

---

## 8. Fuera de alcance (recordatorio)

Endpoints `POST/GET/PATCH/DELETE /plans/{id}/movements` (slice posterior: validación + cablear el motor +
borrado orquestado), los demás motores de la familia, y el `PlanEngine`.
