# Endpoints transversales de obligations (6c) — Diseño

> Sub-slice **6c** (último) del sub-proyecto #6 de **Obligaciones**. Los 2 endpoints transversales a los 3
> kinds: `DELETE /obligations/{id}` (hard-delete con dos checks) y `POST /obligations/{id}/acknowledge`
> (reconocer findings). Cierran el subdominio. El *qué* está en Notion → Endpoints → Obligaciones → DELETE
> obligations / POST acknowledge.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tabla `obligations`, `cash_flow_entries`/`cash_flow_payments`, los 3 motores
  (`materialize_expense`/`debt`/`open_debt`), `DebtOut` (schema, reusado), maestras (todo en `main`).
- **Cierre:** rama `feat/endpoints-obligations`, **squash-merge** a `main`.

---

## 1. Alcance

- **Router** `app/routers/obligations.py` (finito, transversal), registrado en `app/main.py`.
- **Servicio** `app/services/obligation_service.py`: `delete_obligation`, `acknowledge_obligation`.
- **Error codes nuevos** en `app/core/errors.py`.
- **Reusa** `DebtOut` (`app/schemas/debt.py`) como representación completa de la obligación en el response del
  acknowledge.

**Fuera de alcance:** nada más — con 6c queda cerrado el subdominio Obligaciones (tablas, 3 motores,
reviewer, y los endpoints de los 3 grupos). La extracción de validadores comunes
(`expense_service`/`debt_service`) sigue diferida (refactor aparte).

---

## 2. Error codes nuevos (`app/core/errors.py`)

- `obligation_has_children` (409, "Borrá primero las obligaciones derivadas de esta.")
- `obligation_has_payments` (409, "No se puede borrar una obligación con pagos confirmados.")
- `obligation_has_no_findings` (409, "Esta obligación no tiene observaciones para reconocer.")

(`not_found` ya existe.) `OBLIGATION_SOURCE_TYPES = ("gasto", "deuda", "deuda_abierta")`.

---

## 3. `DELETE /obligations/{id}` → 204

Transversal a los 3 kinds (misma lógica). Todo en una transacción; **hard-delete**.

**Validaciones (en orden):**
1. Obligación con `id` y `user_id` = token → si no, `not_found` (404). (No hace falta filtrar por kind: es
   cualquier obligación del usuario.)
2. **Check (a) — sin hijas:** `SELECT count(*) FROM obligations WHERE origin_obligation_id = id`. Si `> 0`
   → `obligation_has_children` (409).
3. **Check (b) — sin pagos reales:** count de `cash_flow_payments` JOIN `cash_flow_entries` por
   `source_type IN OBLIGATION_SOURCE_TYPES`, `source_id = id`, `plan_id IS NULL`. Si `> 0` →
   `obligation_has_payments` (409). (Los pagos **planificados** —`plan_id` no NULL— no cuentan.)

**Borrado orquestado:**
1. `DELETE FROM cash_flow_entries WHERE source_type IN OBLIGATION_SOURCE_TYPES AND source_id = id` (sus
   `cash_flow_payments` —solo planificados, por el check (b)— caen por `ON DELETE CASCADE`).
2. `db.delete(obligation)` (o `DELETE FROM obligations WHERE id = id`).
3. `commit`. Response **204** sin body.

`source_id` no es FK reforzable (polimórfica), por eso el backend orquesta el delete de las entries a mano.

---

## 4. `POST /obligations/{id}/acknowledge` → 200

Transversal. Body vacío (`{}`). Todo en una transacción.

**Validaciones:**
1. Obligación con `id` y `user_id` = token → si no, `not_found` (404).
2. `obligation.review_findings != '[]'` (tiene findings sin reconocer) → si está vacío,
   `obligation_has_no_findings` (409).

**Update de 3 columnas, preservando `updated_at`:**
```python
db.execute(
    update(Obligation)
    .where(Obligation.id == obligation.id)
    .values(review_findings="[]", user_acknowledged_at=datetime.now(timezone.utc),
            is_ready=True, updated_at=obligation.updated_at)
)
```
- `review_findings = '[]'`, `user_acknowledged_at = now`, `is_ready = True`.
- **`updated_at` se preserva** (se pasa su valor actual para que el `onupdate=now()` no lo pise): reconocer no
  es un cambio de datos de negocio (mismo patrón que `select_plan`). `reviewed_at` tampoco se toca.
- **No re-corre el reviewer:** el usuario acepta los findings tal cual.

**Post-update: invocar el motor por kind.** El acknowledge dejó `is_ready = true`; hasta ahora la obligación
no tenía entries (el motor había hecho no-op por los findings). En la misma transacción se invoca el motor
del subdominio según el `obligation_kind` (vía join al tipo): `gasto` → `materialize_expense`; `deuda` →
`materialize_debt`; `deuda_abierta` → `materialize_open_debt`. Pasa el `obligation_id`; el motor relee y, con
`is_ready = true`, materializa. Excepción del motor → rollback total.

`commit` → `db.refresh(obligation)` → **`DebtOut.from_model(obligation)`** (200).

---

## 5. Decisiones, con su porqué

- **Router/servicio `obligations` transversal:** la lógica de DELETE y acknowledge es idéntica para los 3
  kinds (Notion); un endpoint polimórfico evita triplicarla en expenses/debts.
- **Hard-delete con dos checks + orquestado:** `obligations` no tiene soft-delete; el `source_id` no es FK,
  por eso el backend borra las entries explícitamente (los pagos planificados se van por cascade). Una
  obligación con impacto real (pagos `plan_id IS NULL`) no se borra — se cierra vía PATCH.
- **Acknowledge preserva `updated_at` y no re-corre el reviewer:** reconocer es metadata del ciclo, no
  cambio de negocio; se acepta el estado actual. El motor sí corre (el gate quedó en `true`).
- **Reuso de `DebtOut` en el response del acknowledge:** es el superset completo de columnas de una
  obligación (para un gasto, los campos de deuda vuelven `null`); evita un 3er schema casi idéntico
  (decisión confirmada en el brainstorming).
- **`user_id` del token, nunca del body.**

---

## 6. Tests (`tests/test_obligations.py`)

Helper `_auth` y siembra: `priority_levels`, `obligation_types` (gasto, deuda `prestamo`, deuda_abierta
`informal`), currency. Crear obligaciones vía los endpoints `POST /expenses` / `POST /debts` (ya existentes)
para tener filas reales con sus entries. Consultas directas a `obligations`/`CashFlowEntry`/`CashFlowPayment`.

- **DELETE éxito:** borrar un gasto recién creado → 204; la fila de `obligations` y sus `cash_flow_entries`
  ya no existen.
- **DELETE deuda_abierta:** 204 (su entry sin fecha también se borra).
- **DELETE `not_found`:** id inexistente → 404; obligación de otro usuario → 404.
- **DELETE con hija → `obligation_has_children`:** crear una obligación, insertar otra con
  `origin_obligation_id` apuntándola, intentar borrar la madre → 409.
- **DELETE con pago real → `obligation_has_payments`:** agregar un `cash_flow_payment` (`plan_id IS NULL`) a
  una entry de la obligación → 409.
- **DELETE con pago planificado → 204:** un `cash_flow_payment` con `plan_id` no bloquea; la obligación y el
  pago planificado se borran (cascade).
- **Acknowledge éxito:** crear una `deuda` que dispara findings (`overdue < financing` → `is_ready=false`, sin
  entries) → `POST acknowledge` → 200, `review_findings=[]`, `is_ready=true`, y ahora **sí hay entries**
  materializadas; `updated_at` no cambió respecto al previo.
- **Acknowledge sin findings → `obligation_has_no_findings`:** obligación lista (`review_findings='[]'`) →
  409.
- **Acknowledge `not_found`:** id inexistente / de otro usuario → 404.
- **Auth:** ambos endpoints sin token → 401.

Regresión `pytest -q` verde.

---

## 7. Plan de implementación (orientativo)

Un slice (`feat/endpoints-obligations`), 3 tasks: (1) error codes + `delete_obligation` + router DELETE +
sus tests, (2) `acknowledge_obligation` + router acknowledge + sus tests, (3) suite completa. TDD por task.
