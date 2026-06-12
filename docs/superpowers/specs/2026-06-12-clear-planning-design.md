# Borrar lo auto-calculado de un plan — diseño

Fecha: 2026-06-12

## Contexto y objetivo

El PlanningEngine genera `cash_flow_payments` auto-generados (`is_auto_generated = true`)
cuando se corre `POST /plans/{plan_id}/planning`. Ese endpoint **borra y regenera**: cada
corrida limpia los auto previos y los vuelve a crear.

Falta una forma de **solo borrar** lo auto-calculado, sin recalcular — para que el usuario
vuelva a un plan "limpio" (solo sus pagos manuales y reales) cuando no quiere la sugerencia
del motor. Este spec define ese endpoint.

## Alcance

- Endpoint `DELETE /plans/{plan_id}/planning` que borra los pagos auto-generados del plan.
- Backend solamente. La web no lo consume todavía (queda disponible vía API/docs hasta que
  sumemos un botón en una iteración futura).

Fuera de alcance: botón en la web; borrar pagos manuales; tocar `cash_flow_entries`.

## 1. Contrato

`DELETE /plans/{plan_id}/planning` (auth requerida).

- Plan inexistente o de otro usuario → `not_found` (404), igual que `run_planning`.
- Borra todos los `cash_flow_payments` del plan con `is_auto_generated = true`.
- **Idempotente:** si no hay ninguno, devuelve 204 igual (no es error).
- Los pagos **manuales** del usuario (`is_auto_generated = false`) y los **reales**
  (`plan_id IS NULL`) no se tocan.
- Respuesta: `204 No Content`. Commit al final.

Espejo del `POST /plans/{plan_id}/planning` ya existente (mismo path, verbo distinto).

## 2. Servicio (DRY)

Hoy el borrado vive inline dentro de `run_planning` (un `delete(CashFlowPayment).where(...)`).
Se extrae a helpers chicos en `app/services/planning/engine.py`, reusados por ambos flujos:

- `_require_plan(db, user, plan_id) -> Plan`: carga el plan y valida pertenencia; `not_found`
  (404) si es None o de otro usuario. Reemplaza el chequeo inline de `run_planning`.
- `_delete_auto_payments(db, plan_id)`: ejecuta el `DELETE` de los auto. **Sin commit** (lo
  maneja quien llama).
- `clear_planning(db, user, plan_id)`: valida con `_require_plan`, llama a
  `_delete_auto_payments`, hace `commit`. Es lo que invoca el endpoint nuevo.
- `run_planning`: pasa a usar `_require_plan` y `_delete_auto_payments` al inicio (sigue su
  transacción y commitea al final, como hoy — sin cambio de comportamiento).

## 3. Router

`app/routers/plans.py` suma el endpoint `DELETE`, delegando en `planning.clear_planning`
(igual que el `POST` delega en `planning.run_planning`). El router no tiene lógica de negocio.

## 4. Errores

| Caso | Código | HTTP |
|---|---|---|
| Plan inexistente o ajeno | `not_found` | 404 |

Sin errores propios adicionales: borrar cero filas es una corrida válida (204).

## 5. Testing (TDD, nivel servicio + endpoint)

`tests/test_planning.py`, con los helpers existentes (`_user`, `_plan`, `_entry`, `_pay`,
`_autos`):

1. Borra solo los auto y deja los manuales: corre `run_planning`, crea un manual aparte,
   `clear_planning` deja `_autos == []` pero el manual sobrevive.
2. Idempotente: `clear_planning` sin auto previos no rompe y deja `_autos == []`.
3. Plan inexistente → `AppError(not_found)`.
4. Plan de otro usuario → `AppError(not_found)`.
5. No toca los auto de otro plan: un auto del plan B sobrevive al `clear_planning` del plan A.
6. Endpoint: `DELETE` con plan propio → 204; con plan inexistente → 404.
7. La suite existente cubre que `run_planning` sigue andando tras el refactor.

## 6. Estructura de archivos

- `app/services/planning/engine.py` — `_require_plan`, `_delete_auto_payments`,
  `clear_planning`; refactor de `run_planning`.
- `app/services/planning/__init__.py` — exporta `clear_planning` además de `run_planning`.
- `app/routers/plans.py` — endpoint `DELETE /plans/{plan_id}/planning` (delega, 204).
- `tests/test_planning.py` — casos §5.
