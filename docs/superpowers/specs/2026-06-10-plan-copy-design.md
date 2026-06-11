# Copia de plan sin auto-generados — Diseño

> Endpoint `POST /plans/{plan_id}/copy` que crea un **plan nuevo** replicando los `plan_movements` y los
> `cash_flow_payments` planificados del origen, **excluyendo los `is_auto_generated=True`** en ambas tablas. Es
> la operación inversa al PlanningEngine: parte de un plan que el motor pudo haber llenado y se queda con el
> "semilla" manual del usuario.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** backend only. Nuevo endpoint + `plan_service.copy_plan`. Sin web.
- **Cierre:** rama `feat/plan-copy`, **squash-merge** a `main`.
- **Dependencia:** `is_auto_generated` en `plan_movements` y `cash_flow_payments` (ya en `main`, commit `43fcca2`).
- **Fuera de alcance:** el PlanningEngine; copiar pagos reales; copiar entries pasadas.

---

## 1. Endpoint y contrato

- **Ruta:** `POST /plans/{plan_id}/copy` (router `plans`, finito → delega en el servicio).
- **Body:** `PlanCopyRequest { name: str }`. `name` requerido y no vacío (se hace `strip`).
- **Respuesta:** `PlanOut` del plan **nuevo**, status `201`.
- **Errores:** plan origen inexistente o de otro usuario → `not_found`; `name` vacío → `name_required` (field
  `name`). Reusa el catálogo de `ErrorCode` existente; no se agregan códigos nuevos.

---

## 2. Algoritmo de copia (`plan_service.copy_plan`, transacción única)

`copy_plan(db, user, plan_id, payload) -> Plan`:

1. **Cargar origen.** `select(Plan).where(id == plan_id, user_id == user.id)`; si no existe → `not_found`.
   Validar `name` (strip, no vacío).
2. **Plan nuevo.** Copia `dial_amount`, `dial_currency_id`, `goal_kind`, `goal_amount`, `goal_currency_id` del
   origen. `name` = del body. `is_default=False`, `is_engine_generated=False`. **No seleccionado:**
   `selected_at = user.created_at` (igual que `create_plan` con `select_on_create=False`). `db.add` + `flush`
   para tener el id nuevo.
3. **Movements.** Por cada `PlanMovement` del origen con `is_auto_generated=False` (orden por `created_at` para
   estabilidad): construir uno nuevo copiando **todos** los campos de negocio (`kind`, `currency_id`,
   `description`, `principal_amount`, `start_date`, `income_duration_months`, `installment_amount`,
   `installment_start_date`, `total_installments`, `financing_rate`, `overdue_rate`, `rates_add_vat`), con
   `plan_id` = nuevo e `is_auto_generated=False`. `db.add` + `flush`. Guardar `movement_map[viejo_id] =
   nuevo_id`. Luego `materialize_plan_movement(db, nuevo_id)` (genera las `cash_flow_entries` nuevas, de hoy al
   horizonte).
4. **Índice de entries nuevas.** Tras materializar todos: `select(CashFlowEntry)` donde `source_id in
   movement_map.values()` y `source_type in {"plan_movimiento", "plan_movimiento_entrada"}`. Indexar por
   `(source_id, source_type, event_date.year, event_date.month, currency_id) -> entry.id`.
5. **Pagos planificados.** `select(CashFlowPayment).where(plan_id == origen, is_auto_generated == False)`. Por
   cada uno, resolver la entry destino:
   - `entry = db.get(CashFlowEntry, pago.cash_flow_entry_id)`.
   - **Entry real/compartida** (`source_type NOT in PLAN_ENTRY_TYPES`): destino = **mismo** `entry.id`.
   - **Entry del propio plan** (`source_type in PLAN_ENTRY_TYPES`): `m_new = movement_map.get(entry.source_id)`.
     Si `m_new is None` → **descartar** el pago (su movement era auto-generado, no está en la copia). Si existe,
     buscar `nuevo_entry_id = índice[(m_new, source_type, año, mes, currency_id)]`; si no está → **descartar**
     (la entry era pasada y la re-materialización hoy→horizonte no la regeneró).
   - Crear `CashFlowPayment(cash_flow_entry_id=destino, amount=pago.amount, note=pago.note, plan_id=nuevo,
     planned_date=pago.planned_date)` (`is_auto_generated` queda `False` por default).
6. **Commit único.** `db.commit()` + `db.refresh(plan_nuevo)`; devolver el plan nuevo. Cualquier excepción
   intermedia hace rollback (transacción atómica controlada por el servicio).

`PLAN_ENTRY_TYPES = {"plan_movimiento", "plan_movimiento_entrada"}` ya existe en `cash_flow_payment_service`; se
reutiliza la constante (importar) en vez de redefinirla.

---

## 3. Qué se excluye / descarta (consecuencias asumidas)

- **No se copian:** `plan_movements` ni `cash_flow_payments` con `is_auto_generated=True`; ni los pagos
  **reales** (`plan_id IS NULL`, no pertenecen a un plan).
- **Se descarta** un pago no-auto cuando su entry destino no existe en la copia:
  - (a) apuntaba a un movement auto-generado (excluido) → sin `movement_map`;
  - (b) apuntaba a una entry **pasada** (`event_date < hoy`) que la materialización hoy→horizonte ya no
    regenera.
  En ambos casos el pago carece de destino válido en el escenario nuevo; descartarlo es lo correcto (no se crea
  un pago colgado ni se viola la restricción "pago de plan-entry ⇒ mismo plan").
- **Por qué la clave de mapeo es `(source_type, año, mes, currency)`** y no el día exacto: la materialización es
  determinista por mes (su reconciliación interna usa esa misma clave), así que el movement copiado produce, mes
  a mes, las mismas entries que el origen para fechas de hoy en adelante.

---

## 4. Archivos

| Archivo | Cambio |
|---|---|
| `app/schemas/plan.py` | Nuevo `PlanCopyRequest { name: str }` |
| `app/services/plan_service.py` | Nueva `copy_plan` (+ helpers de mapeo); convive con `delete_plan`, que ya orquesta plan+movements+entries+pagos |
| `app/routers/plans.py` | Nueva ruta `POST /plans/{plan_id}/copy` → `PlanOut` |
| `tests/test_plan_copy.py` | Tests TDD (ver §5) |

---

## 5. Tests

Archivo nuevo `tests/test_plan_copy.py` (reusa los helpers de `tests/test_plans.py`/`test_plan_movements.py`):

- **Metadata + estado:** copia `dial_amount`/`goal_*` del origen; usa el `name` del body; el plan nuevo **no**
  queda seleccionado y no es default; el origen no se modifica.
- **Excluye auto:** un movement y un pago `is_auto_generated=True` en el origen **no** aparecen en la copia; los
  `is_auto_generated=False` sí.
- **Movements materializan:** los movements copiados tienen id nuevo, `plan_id` nuevo, y generan
  `cash_flow_entries` nuevas (distintas de las del origen).
- **Pago contra entry compartida:** un pago planificado contra un gasto/obligación se copia con el **mismo**
  `cash_flow_entry_id` y `plan_id` nuevo.
- **Pago contra movement propio:** un pago planificado contra una entry `plan_movimiento` del origen se
  **re-engancha** a la entry nueva del movement copiado (entry distinta, perteneciente al plan nuevo); el pago
  resultante respeta la restricción "plan-entry ⇒ mismo plan".
- **Descarte:** un pago no-auto contra un movement auto-generado (excluido) **no** se copia.
- **Pago real no se copia:** un `cash_flow_payment` con `plan_id IS NULL` no entra en la copia.
- **404:** copiar un plan de otro usuario o inexistente → `not_found`.
- **`name` vacío:** → `name_required`.

---

## 6. Plan (orientativo)

Un slice (`feat/plan-copy`), TDD: schema `PlanCopyRequest` → `copy_plan` en el servicio (plan nuevo → movements
+ materialización → índice de entries → pagos con re-enganche/descarte) → ruta → suite verde → cierre
(squash-merge). Sin Notion.
