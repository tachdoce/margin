# Endpoints de `plan_movements` (CRUD) — Diseño

> Los 4 endpoints de los movimientos hipotéticos de un plan: `POST/GET/PATCH/DELETE
> /plans/{id}/movements`. Cablean el motor `materialize_plan_movement` (ya existente) y aplican la validación
> kind↔columnas. Cierra el flujo de simulación de planes. El *qué* vive en Notion → Endpoints → Flujo de
> dinero → POST/GET/PATCH/DELETE plan-movements, y BD → Flujo de dinero → plan_movements.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** `plan_movements` (tabla), `plans` (+ sus endpoints, en `main`), `CashFlowEngine.plan_movements`
  (motor en `main`), `cash_flow_entries`/`cash_flow_payments`, `currencies`, `users`.
- **Cierre:** rama `feat/plan-movements-endpoints`, **squash-merge** a `main`.

---

## 1. Alcance

Cuatro endpoints bajo `/plans/{id}/movements`, todos protegidos, `user_id` siempre del token (subiendo
`plan.user_id`). Router nuevo `app/routers/plan_movements.py`, servicio nuevo
`app/services/plan_movement_service.py`, schemas nuevos `app/schemas/plan_movement.py`, 4 error codes nuevos.
POST/PATCH corren el motor; DELETE orquesta el borrado.

**Fuera de alcance:** el `PlanEngine`, los endpoints de `cash_flow_*` (timeline), y cualquier vista web.

---

## 2. Arquitectura

- **Router** `app/routers/plan_movements.py` (registrado en `main.py`), finito.
- **Servicio** `app/services/plan_movement_service.py`: `create_movement`, `list_movements`,
  `update_movement`, `delete_movement`, + helpers de validación. Importa
  `materialize_plan_movement` de `app.services.cash_flow.plan_movements`.
- **Schemas** `app/schemas/plan_movement.py`:
  - `PlanMovementCreate`: `kind: str`, `currency_id: int`, `description: str | None = None`,
    `principal_amount: Decimal`, `start_date: date`, `income_duration_months: int | None = None`,
    `installment_amount: Decimal | None = None`, `installment_start_date: date | None = None`,
    `total_installments: int | None = None`, `financing_rate: Decimal | None = None`,
    `overdue_rate: Decimal | None = None`, `rates_add_vat: bool | None = None`.
  - `PlanMovementUpdate`: todos opcionales (semántica PATCH vía `model_fields_set`); `kind` también está pero
    se ignora.
  - `PlanMovementOut` (con `from_model`): `id, plan_id, kind, currency_id, description, principal_amount,
    start_date, income_duration_months, installment_amount, installment_start_date, total_installments,
    financing_rate, overdue_rate, rates_add_vat`. Sin timestamps. Plata/tasas como **string** (convención).
- **Error codes nuevos** en `app/core/errors.py`:
  - `default_plan_no_movements` (409, "El plan actual no admite movimientos. Creá un plan nuevo para simular escenarios.")
  - `kind_invalid` (422, "Tipo de movimiento no válido.")
  - `installments_invalid` (422, "Las cuotas no son válidas.")
  - `movement_fields_invalid` (422, "Los datos del movimiento no coinciden con su tipo.")
  - (`not_found`, `amount_invalid`, `currency_not_available`, `empty_patch` ya existen.)

`MOVEMENT_KINDS = ("ingreso", "deuda_informal", "prestamo")`.

---

## 3. Validación kind↔columnas (corazón del feature)

Columnas opcionales agrupadas:
- **income field:** `income_duration_months`.
- **installment fields:** `installment_amount`, `installment_start_date`, `total_installments`.
- **rate fields:** `financing_rate`, `overdue_rate`, `rates_add_vat`.

Reglas de qué campos **pueden** traer valor por kind (cualquier campo fuera de su grupo que venga con valor →
`movement_fields_invalid`):
- **`ingreso`**: permite `income_duration_months`. Prohíbe installment + rate fields.
- **`deuda_informal`**: no permite ninguno de los opcionales (ni income, ni installment, ni rate).
- **`prestamo`**: permite installment + rate fields. **No** acepta `income_duration_months` en el body con
  valor distinto de `1` (en POST no viene; en PATCH solo se acepta `1`); el backend lo fija en `1`.

Reglas propias de `prestamo` (cuotas), tras pasar la consistencia:
- `installment_amount` presente y `> 0` (si `<= 0` → `amount_invalid`; si ausente → `installments_invalid`).
- `installment_start_date` presente (ausente → `installments_invalid`).
- `total_installments` presente y `>= 1` (ausente o `< 1` → `installments_invalid`).

Helper único `_validate_movement_fields(kind, values)` (recibe un dict de los campos presentes con valor),
reusado por POST (sobre el body) y PATCH (sobre el estado final). El motor confía en esta validación: no
revalida.

---

## 4. `POST /plans/{id}/movements` → 201

**Validaciones (en orden):**
1. Plan con `id` y `user_id = user.id`. Si no → `not_found` (404).
2. `plan.is_default == False`. Si es el default → `default_plan_no_movements` (409).
3. `kind in MOVEMENT_KINDS`. Si no → `kind_invalid` (422).
4. `currency_id` existe y `country_code == user.country_code`. Si no → `currency_not_available` (422).
5. `principal_amount > 0`. Si no → `amount_invalid` (422).
6. Consistencia kind↔columnas (§3). Si falla → `movement_fields_invalid` (422).
7. Si `prestamo`: reglas de cuotas (§3) → `amount_invalid` / `installments_invalid`.

**Insert:** campos comunes del body; los específicos según kind; las columnas que no aplican en `NULL`. En
`prestamo`, `income_duration_months = 1` (constante del kind, no del body). `rates_add_vat = payload.rates_add_vat
if not None else True` (la columna es NOT NULL sin default; el servicio siempre la setea).

**Motor:** `db.flush()` → `materialize_plan_movement(db, movement.id)` → `db.commit()` → `db.refresh()`.
Rollback total si el motor falla. Response 201 con `PlanMovementOut`.

---

## 5. `GET /plans/{id}/movements` → 200

Solo lectura. Valida plan con `id` y `user_id = user.id` (si no → `not_found` 404). Lee los `plan_movements`
con `plan_id = id`, ordenados por `start_date ASC`. Devuelve **array** `list[PlanMovementOut]` (puede ser
`[]`; el default siempre devuelve `[]` porque no tiene movimientos).

---

## 6. `PATCH /plans/{id}/movements/{movement_id}` → 200

**Validaciones:**
1. Plan con `id` y `user_id = user.id`. Si no → `not_found` (404).
2. `plan_movements` con `id = movement_id` y `plan_id = id`. Si no → `not_found` (404).
3. `kind` en el body se **ignora** (no cambia el tipo, no es error). El `kind` que vale es el de la fila.
4. El body trae al menos un campo editable (de los que no son `kind`). Si no → `empty_patch` (422).
5. `currency_id` (si viene): válido y del país. Si no → `currency_not_available`.
6. `principal_amount`/`installment_amount` (si vienen): `> 0`. Si no → `amount_invalid`.
7. Consistencia kind↔columnas (§3) sobre los campos **presentes** contra el `kind` de la fila: un campo de
   otro kind → `movement_fields_invalid`. En `prestamo`, `income_duration_months` solo se acepta con valor `1`.
8. Estado final de `prestamo`: si tras el PATCH quedan cuotas inconsistentes (falta
   `installment_amount`/`installment_start_date`/`total_installments` en la fila, o `total_installments < 1`)
   → `installments_invalid`.

**Update:** solo las columnas presentes. `id`, `plan_id`, `kind`, `created_at` no se tocan; `updated_at`
`onupdate` natural. **Motor:** `flush` → `materialize_plan_movement` → `commit` → `refresh`. Response 200 con
`PlanMovementOut`.

---

## 7. `DELETE /plans/{id}/movements/{movement_id}` → 204

**Validaciones:** plan (`not_found` 404) y movimiento de ese plan (`not_found` 404). Sin errores de negocio
(no hay 409; las entries del plan no tienen pagos reales).

**Borrado orquestado (no invoca al motor):**
1. `DELETE cash_flow_entries WHERE source_type IN ('plan_movimiento','plan_movimiento_entrada') AND source_id
   = movement_id` (los pagos planificados que colgaran caen por `ON DELETE CASCADE`).
2. `DELETE plan_movements WHERE id = movement_id`.

`commit`. Response 204 sin body.

---

## 8. Decisiones, con su porqué

- **Router/servicio dedicados (no en plans.py):** la validación kind↔columnas es sustancial; un módulo propio
  mantiene `plan_service` enfocado en el plan y este en sus movimientos.
- **Helper de validación compartido POST/PATCH:** una sola fuente de verdad para la consistencia kind↔columnas;
  en PATCH se evalúa sobre el estado final.
- **El motor se cabla en POST/PATCH, el DELETE orquesta directo:** mismo patrón que incomes; el motor no tiene
  rama de borrado de fuente.
- **`income_duration_months=1` lo fija el backend en préstamo:** constante del kind (la plata entra una vez),
  no elección del usuario (Notion).
- **`rates_add_vat` lo setea siempre el servicio (default True):** la columna es NOT NULL sin server_default
  (decisión del slice tabla); el backend asigna el valor, como con los otros booleanos de datos de usuario.
- **`user_id` vía `plan.user_id`, nunca del body.**

---

## 9. Tests (`tests/test_plan_movements.py`)

Sembrando country UY + currency + usuario (con su default) y creando un plan no-default vía `POST /plans`.
Helpers `_auth`, `_plan` (crea un plan no-default y devuelve su id), y consultas directas a `CashFlowEntry`/
`CashFlowPayment` donde haga falta.

- **POST:** crea `ingreso` / `deuda_informal` / `prestamo` (201, fila correcta, `income_duration_months=1` en
  préstamo); crea y **materializa** (aparecen `cash_flow_entries` del movimiento); plan default → 409
  `default_plan_no_movements`; `kind` inválido → `kind_invalid`; `principal_amount<=0` → `amount_invalid`;
  campo de otro kind (ej. `installment_amount` en `ingreso`) → `movement_fields_invalid`; préstamo sin
  `total_installments` → `installments_invalid`; moneda de otro país → `currency_not_available`; plan de otro
  usuario → 404; requiere auth.
- **GET:** lista ordenada por `start_date`; default → `[]`; plan de otro usuario → 404.
- **PATCH:** edita `principal_amount`/`description`; ajusta cuota/tasa de un préstamo (re-materializa);
  `kind` en el body se ignora; campo de otro kind → `movement_fields_invalid`; body vacío → `empty_patch`;
  movimiento de otro plan/usuario → 404.
- **DELETE:** borra el movimiento + sus `cash_flow_entries` + un `cash_flow_payment` planificado; movimiento
  inexistente → 404.

Regresión `pytest -q` verde.

---

## 10. Plan de implementación (orientativo)

Un slice (`feat/plan-movements-endpoints`), 3 tasks: (1) schemas + error codes + helper de validación +
`POST` + `GET` (+ router registrado), (2) `PATCH`, (3) `DELETE`.
