# Slice 2 — `CashFlowEngine.incomes` (motor de materialización) — Diseño

> Segundo slice de conectar **Ingresos** con la **línea de tiempo del flujo de caja**. Agrega el motor que
> traduce cada `incomes` vigente en filas de `cash_flow_entries`. Este slice agrega **solo el motor** (lógica
> de aplicación), sin cablearlo a los endpoints (eso es el slice 3). El *qué* del producto vive en
> Notion → Backend → Engines → CashFlowEngine (familia + subpágina `incomes`) y BD → Flujo de dinero →
> `cash_flow_entries`.

- **Fecha:** 2026-06-07
- **Estado:** aprobado para implementar
- **Depende de:** `incomes`, `cash_flow_entries`, `cash_flow_payments`, `currencies`, `users` (todos en `main`;
  las tablas de flujo de caja entraron en el slice 1).
- **Cierre:** rama `feat/cashflow-engine-incomes`, **squash-merge** a `main`.

---

## 1. Alcance

Paquete nuevo `app/services/cash_flow/` con dos piezas:

- **`date_utils.compute_event_date(...)`** — función canónica de fechado, compartida por toda la familia
  `CashFlowEngine`. Se construye y testea sola.
- **`incomes.materialize_income(...)`** — el motor del subdominio incomes: (re)materializa las
  `cash_flow_entries` de un income por UPSERT contra su clave lógica.

**No entra:** los endpoints de ingresos (no se cablea el motor todavía), el borrado híbrido, ni los demás
motores de la familia. Al terminar, el motor existe y está testeado, pero nadie lo invoca aún.

---

## 2. `compute_event_date` (canónica de la familia)

**Ubicación:** `app/services/cash_flow/date_utils.py`.

**Firma:** `compute_event_date(year: int, month: int, target_day: int, shift_weekends: bool) -> date`

**Lógica:**

1. **Clamp de fin de mes:** `day = min(target_day, último_día_del_mes(year, month))`. Ej.: `target_day=31` en
   febrero → 28 (29 en año bisiesto). El último día del mes sale de `calendar.monthrange(year, month)[1]`.
2. **Corrimiento de fin de semana** (solo si `shift_weekends=True`): si `date(year, month, day)` cae sábado o
   domingo, se corre al **lunes siguiente**; si ese lunes cae en el mes siguiente, se corre al **viernes
   anterior**. Con `shift_weekends=False` la fecha queda literal (solo se aplicó el clamp del paso 1).
3. Devuelve el `date` resultante. **Nunca sale del mes objetivo.**

Es la única implementación de fechado de la familia: los motores la invocan, no la reimplementan. Feriados:
fuera de alcance (extensión futura dentro de esta misma función, sin tocar a quien la llama).

---

## 3. `materialize_income` (motor del subdominio)

**Ubicación:** `app/services/cash_flow/incomes.py`.

**Firma:** `materialize_income(db: Session, income_id: uuid.UUID, *, today: date | None = None,
horizon: date = date(2027, 12, 31)) -> None`

### 3.1 Lectura y transacción

- `today` se resuelve a `date.today()` si no se pasa.
- Lee el income con lock de fila: `select(Income).where(Income.id == income_id).with_for_update()`. Si no
  existe → `return` (no-op defensivo; el endpoint siempre pasa un id válido recién persistido).
- `user_id`, `currency_id`, `amount`, `shift_weekends` y la forma salen del income releído. **Nunca** por
  parámetro ni del contexto de request.
- **No hace `commit`** — la transacción la controla el caller (el endpoint, en slice 3). Si lanza excepción,
  el caller hace rollback.

### 3.2 Conjunto objetivo (las entries que deberían existir)

- Si `income.deleted_at is not None` → conjunto **vacío** (un income borrado no proyecta futuro).
- **Recurrente infinito** (`is_monthly_recurring = True`): una fila por mes desde el mes de `today` hasta el
  mes de `horizon` inclusive. Para cada mes: `event_date = compute_event_date(año, mes, income.payment_day,
  income.shift_weekends)`. Se incluye **solo si** `event_date >= today` (el mes actual puede quedar afuera si
  el día ya pasó).
- **Duración fija** (`is_monthly_recurring = False`): `total_months` meses consecutivos empezando en
  `first_income_date`. Para cada mes: `event_date = compute_event_date(año, mes, first_income_date.day,
  income.shift_weekends)`. Se incluye solo si `today <= event_date <= horizon`. El cobro único es
  `total_months = 1` (una sola fila).

Cada fila objetivo lleva: `is_income=True`, `source_type='ingreso'`, `source_id=income.id`,
`event_date` calculado, `amount=income.amount`, `currency_id=income.currency_id`, `user_id=income.user_id`,
`financing_rate=None`, `overdue_rate=None`, y las columnas de tarjeta (`issue_year`, `issue_month`,
`minimum_payment`) en `None`.

### 3.3 Reconciliación por UPSERT

**Clave lógica de la entry de ingreso:** `(año(event_date), mes(event_date), currency_id)`, con
`source_type='ingreso'` y `source_id=income.id` fijos para todas. (`currency_id` es constante porque un income
tiene una sola moneda, pero forma parte de la clave por consistencia con la familia.)

1. Cargar las entries existentes del income: `select(CashFlowEntry).where(source_type='ingreso',
   source_id=income.id)`. Indexarlas por clave lógica.
2. Por cada fila objetivo: si la clave **existe** → **UPDATE** de `amount` y `event_date`; si **no existe** →
   **INSERT** de una entry nueva. El UPDATE de `amount` se aplica aunque la entry tenga pago real (Notion:
   actualizar el monto es libre).
3. Las existentes que quedaron **fuera** del conjunto objetivo se **borran solo si** son futuras
   (`event_date >= today`) **y** no tienen pago real (un `cash_flow_payments` con `plan_id IS NULL`
   imputado a esa entry). Las pasadas y las con pago real **sobreviven** (preservan la historia). Los pagos
   planificados que colgaran de una entry borrada se van por `ON DELETE CASCADE`.

La unicidad de la clave la garantiza el motor corriendo secuencial bajo el lock `FOR UPDATE` del income; no
hay UNIQUE en BD.

**Por qué la clave es por mes y no por día (caso: cambia el día de cobro).** Si un income recurrente pasa de
`payment_day = 5` a `payment_day = 20`, para cada mes futuro la entry existente (`event_date` el día 5) y la
objetivo (el día 20) comparten la **misma clave lógica** `(año, mes, currency_id)` — porque la clave no
incluye el día. La reconciliación entra por la rama **UPDATE** y mueve el `event_date` del 5 al 20 **in
place**: la fila conserva su `id` y los `cash_flow_payments` imputados; no se duplica ni se borra. El nuevo
`event_date` se calcula con `compute_event_date(año, mes, 20, income.shift_weekends)`, así que respeta el
corrimiento de fin de semana. **Afecta este mes y los siguientes:** toda fila cuyo **nuevo** `event_date` sea
`>= today` se mueve (incluido el mes en curso, si el día 20 de este mes todavía no pasó). Caso borde: si el
nuevo día de este mes ya quedó atrás (`día 20 < today`), el mes en curso no entra al conjunto objetivo y su
entry queda como estaba — no se reprograma una fecha del mes que ya pasó. Si la clave incluyera el día, el
cambio se traduciría en delete + insert, perdiendo identidad y pagos — por eso es por mes.

---

## 4. Decisiones, con su porqué

- **`today`/`horizon` inyectables (parámetros con default):** la materialización depende de "hoy" y dentro de
  una transacción Postgres `now()` es constante; con defaults el código de producción no cambia y los tests
  son deterministas (controlan qué meses caen en rango). `horizon` por defecto `2027-12-31` (Notion).
- **El motor no commitea:** lo controla el endpoint (un solo punto de commit/rollback por operación), igual
  que `create_default_plan` con `register_user`.
- **Lee la fila con `FOR UPDATE` (no la recibe por parámetro):** trabaja con el estado ya actualizado por el
  endpoint y serializa ejecuciones sobre el mismo income, sosteniendo la unicidad de la clave sin UNIQUE.
- **Income inexistente → no-op:** defensivo; el motor es un traductor sync, no valida reglas de negocio.
- **`compute_event_date` canónica y aparte:** la usarán todos los motores; una sola implementación evita
  divergencias de fechado.
- **Borrado acotado a futuras sin pago real:** el motor nunca destruye historia; el borrado de filas con pago
  real lo maneja el endpoint (slice 3), no el motor.

---

## 5. Tests

`tests/test_cash_flow_date_utils.py` (función pura, sin DB):
- clamp de fin de mes: `(2026, 2, 31)` → `2026-02-28`; bisiesto `(2024, 2, 31)` → `2024-02-29`.
- `shift_weekends=True`: una fecha en sábado → lunes siguiente; en domingo → lunes siguiente; un lunes que
  caería en el mes siguiente → viernes anterior (caso fin de mes).
- `shift_weekends=False`: una fecha que cae fin de semana queda literal (solo aplica el clamp).

`tests/test_cashflow_engine_incomes.py` (motor directo, con `today`/`horizon` fijos; sembrando country UY +
currency + income_type + user + income):
- **recurrente infinito:** genera una entry por mes desde `today` hasta `horizon`; verifica count,
  `event_date`, `amount`, `is_income=True`, `source_type='ingreso'`, `source_id`.
- **meses pasados:** con `payment_day` ya vencido en el mes de `today`, ese mes no se materializa.
- **duración fija:** `total_months=3` desde `first_income_date` → 3 entries consecutivas.
- **cobro único:** `total_months=1` → 1 entry.
- **soft-deleted:** `deleted_at` no NULL → conjunto vacío (no quedan entries futuras).
- **idempotencia:** correr el motor 2× deja el mismo conjunto (no duplica).
- **cambio de `amount`:** re-correr con otro monto actualiza las entries existentes sin duplicar.
- **cambio de `payment_day` (5 → 20):** re-correr mueve el `event_date` de cada mes futuro del día 5 al 20
  **in place** — mismo count, misma fila (mismo `id`), sin duplicar; respetando `shift_weekends`.
- **reconciliación con borrado:** achicar `total_months` borra las futuras sin pago real; una entry con un
  `cash_flow_payments` real imputado sobrevive.
- **corrimiento de finde:** un income con `shift_weekends=True` cuyo día cae fin de semana produce entries en
  día hábil.

Regresión `pytest -q` verde.

---

## 6. Fuera de alcance (recordatorio)

Endpoints de ingresos cableados al motor y borrado híbrido hard/soft (slice 3); los demás motores de la
familia (`expenses`, `debts`, `open_debts`, `plan_movements`, `credit_cards`); feriados en `compute_event_date`.
