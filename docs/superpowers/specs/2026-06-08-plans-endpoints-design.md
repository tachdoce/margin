# Endpoints de planes (CRUD + select) — Diseño

> Los 5 endpoints del recurso `plans`: `POST /plans`, `GET /plans`, `PATCH /plans/{id}`,
> `DELETE /plans/{id}` y `POST /plans/{id}/select`. Crean/listan/editan/borran/activan los planes de
> simulación del usuario. Ningún endpoint corre el `CashFlowEngine` (el CRUD de planes no materializa; eso lo
> hacen los `plan_movements`, slice posterior). El *qué* vive en Notion → Endpoints → Flujo de dinero →
> POST/GET/PATCH/DELETE plans + POST plans select, y BD → Flujo de dinero → plans.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** `plans` (tabla en `main`), `currencies`, `users`, `cash_flow_entries`/`cash_flow_payments`/
  `plan_movements` (todos en `main`; el DELETE los barre). Reusa `create_default_plan` ya existente.
- **Cierre:** rama `feat/plans-endpoints`, **squash-merge** a `main`.

---

## 1. Alcance

Cinco endpoints, todos protegidos (`Depends(get_current_user)`), `user_id` siempre del token. El cambio:
router nuevo `app/routers/plans.py`, extender `app/services/plan_service.py`, schemas nuevos
`app/schemas/plan.py`, y 5 error codes nuevos. **Ningún endpoint corre el engine.**

**Fuera de alcance:** los endpoints de `plan_movements` (slice siguiente), el `PlanEngine`, y cualquier vista
web.

---

## 2. Arquitectura

- **Router** `app/routers/plans.py` (registrado en `app/main.py`), finito: delega en el servicio.
- **Servicio** `app/services/plan_service.py`: suma `create_plan`, `list_plans`, `update_plan`,
  `delete_plan`, `select_plan`. Se refactoriza la derivación de moneda de `create_default_plan` a un helper
  `_legal_tender_currency(db, user) -> Currency` (`is_legal_tender = true` AND `country_code = user.country_code`),
  que `create_default_plan` y `create_plan`/`update_plan` reusan. `create_default_plan` no cambia de
  comportamiento.
- **Schemas** `app/schemas/plan.py`:
  - `PlanCreate`: `name: str`, `dial_amount: Decimal`, `goal_kind: str | None = None`,
    `goal_amount: Decimal | None = None`, `select_on_create: bool = False`.
  - `PlanUpdate`: `name`, `dial_amount`, `goal_kind`, `goal_amount` — todos opcionales (semántica PATCH vía
    `model_fields_set`).
  - `PlanOut` (con `from_model`): `id, name, is_default, is_engine_generated, selected_at, dial_amount,
    dial_currency_id, goal_kind, goal_amount, goal_currency_id`. Sin timestamps internos. Plata como **string**
    (convención del proyecto; Pydantic serializa Decimal como string).
- **Error codes nuevos** en `app/core/errors.py`:
  - `name_required` (422, "El plan necesita un nombre.")
  - `dial_amount_invalid` (422, "El monto del dial debe ser mayor o igual a 0.")
  - `goal_invalid` (422, "El objetivo no es válido.")
  - `empty_patch` (422, "No hay cambios para aplicar.")
  - `default_plan_undeletable` (409, "El plan actual no se puede borrar.")
  - (`not_found` y `unauthenticated` ya existen.)

`GOAL_KINDS = ("ahorro_total",)` — el único valor válido de `goal_kind` (espeja el enum nativo `plan_goal_kind`).

---

## 3. `POST /plans` → 201

Crea un plan **no-default** del usuario.

**Validaciones (en orden):**
1. `name` presente y no vacío tras `strip()`. Si no → `name_required`.
2. `dial_amount >= 0`. Si no → `dial_amount_invalid`.
3. Objetivo todo-o-nada: o vienen `goal_kind` **y** `goal_amount`, o ninguno. Si viene solo uno →
   `goal_invalid`. Si vienen: `goal_kind in GOAL_KINDS` y `goal_amount > 0`. Si no → `goal_invalid`.

**Derivaciones (backend, no del body):**
- `dial_currency_id` = `_legal_tender_currency(db, user).id`.
- `goal_currency_id` = la misma, **solo si hay objetivo**; si no, `None`.
- `selected_at` = `now(UTC)` si `select_on_create` es `True`; si no, `user.created_at` (valor viejo → no nace
  activo).

**Insert:** `user_id=user.id`, `name=name.strip()`, `is_default=False`, `is_engine_generated=False`, y los
campos de arriba. `commit` + `refresh`. **No corre engine.** Response 201 con `PlanOut`.

---

## 4. `GET /plans` → 200

Solo lectura. Lee los `plans` con `user_id = user.id`, ordenados por `selected_at DESC, created_at DESC`.
Devuelve un **array** `list[PlanOut]` (nunca vacío: siempre está el default). El frontend interpreta el primero
como activo.

---

## 5. `PATCH /plans/{id}` → 200

Edita `name`, `dial_amount`, objetivo. Aplica al default y a los no-default.

**Validaciones:**
1. Plan con `id` y `user_id = user.id`. Si no → `not_found` (404).
2. El body trae al menos un campo de `{name, dial_amount, goal_kind, goal_amount}` en `model_fields_set`. Si
   no → `empty_patch`.
3. Si `name` presente: no `None` y no vacío tras `strip()` (no se puede nulear/vaciar el nombre). Si no →
   `name_required`.
4. Si `dial_amount` presente: no `None` y `>= 0`. Si no → `dial_amount_invalid`.
5. Objetivo sobre el **estado final** (`final_goal_kind`/`final_goal_amount` = el valor del body si está en
   `model_fields_set`, si no el de la fila): ambos con valor o ambos `None`. Si queda uno solo → `goal_invalid`.
   Si quedan con valor: `goal_kind in GOAL_KINDS` y `goal_amount > 0`. Si no → `goal_invalid`.

**Derivación de `goal_currency_id`:** si el estado final tiene objetivo → `_legal_tender_currency(db, user).id`;
si queda sin objetivo → `None`. `dial_currency_id` no se toca.

**Update:** solo las columnas presentes (+ `goal_currency_id` derivada). No se tocan `id`, `user_id`,
`is_default`, `is_engine_generated`, `selected_at`, `created_at`. `updated_at = now()` (lo maneja `onupdate`).
**No corre engine.** Response 200 con `PlanOut`.

> Nota: los campos nullable del objetivo (`goal_kind`/`goal_amount`) sí aceptan `null` explícito en el PATCH
> (es la forma de **quitar** el objetivo: ambos en `null`). Por eso NO se les aplica la regla
> `field_not_nullable` de incomes; la consistencia la cubre la validación de objetivo todo-o-nada.

---

## 6. `DELETE /plans/{id}` → 204

**Validaciones:**
1. Plan con `id` y `user_id = user.id`. Si no → `not_found` (404).
2. `is_default == False`. Si es el default → `default_plan_undeletable` (409).

**Borrado orquestado (4 pasos, una transacción, SQL directo con `delete()`):**
1. `DELETE cash_flow_payments WHERE plan_id = {id}` — todos los pagos planificados del plan, incluso los
   imputados a entries **reales** (que el cascade de entries no alcanzaría).
2. `DELETE cash_flow_entries WHERE source_type IN ('plan_movimiento','plan_movimiento_entrada') AND source_id
   IN (SELECT id FROM plan_movements WHERE plan_id = {id})` — las entries de los movimientos del plan.
3. `DELETE plan_movements WHERE plan_id = {id}`.
4. `DELETE` la fila de `plans` (`id = {id}`).

`commit`. Response 204 sin body. **No corre engine.**

> El default es indestructible (paso de validación 2). Borrar el plan activo es válido: el frontend pasa a
> tomar el de mayor `selected_at` entre los que quedan (siempre está el default).

---

## 7. `POST /plans/{id}/select` → 200

**Validaciones:** plan con `id` y `user_id = user.id`. Si no → `not_found` (404). Sin errores de negocio
(cualquier plan, incluido el default, se puede seleccionar).

**Update:** `selected_at = now(UTC)`. **No se toca `updated_at`** (seleccionar es metadata de navegación, no
cambio de datos de negocio — por eso es endpoint aparte y no parte del PATCH). `commit` + `refresh`. **No corre
engine.** Response 200 con `PlanOut`.

---

## 8. Decisiones, con su porqué

- **`select_at` separado del PATCH:** editar un plan no debe volverlo activo; solo `select` cambia
  `selected_at`. Por eso `updated_at` no se toca en select y `selected_at` no se toca en PATCH.
- **`select_on_create` no se persiste:** solo decide qué `selected_at` se escribe al insertar (now vs
  `user.created_at`). No es columna.
- **Monedas derivadas del país, nunca del body:** mismo criterio del resto del backend.
- **GET devuelve array pelado (sin wrapper):** así lo define el contrato de Notion. (Incomes usó wrapper; acá
  se sigue el contrato del recurso plans.)
- **DELETE barre pagos planificados por `plan_id` primero:** un plan puede tener pagos planificados sobre
  entries reales; el cascade de entries no los alcanza, por eso el paso 1 explícito.
- **Ningún endpoint corre el engine:** el CRUD de planes no materializa `cash_flow_entries`; solo los
  `plan_movements` lo hacen (Notion).
- **Helper `_legal_tender_currency` compartido:** evita duplicar la query de moneda principal entre
  `create_default_plan`, `create_plan` y `update_plan`.

---

## 9. Tests (`tests/test_plans.py`)

Sembrando country UY + currency legal + un usuario (que ya nace con su plan default vía registro, o se siembra
el plan default). Helpers `_auth`, y consultas directas a `Plan`/`CashFlowEntry`/`CashFlowPayment` donde haga
falta.

- **POST:** crea sin objetivo; crea con objetivo (deriva `goal_currency_id`); `select_on_create=true` deja el
  plan primero en el `GET`; sin `select_on_create` nace inactivo (`selected_at` viejo, queda detrás del
  default); `name` vacío → `name_required`; `dial_amount` negativo → `dial_amount_invalid`; objetivo a medias
  → `goal_invalid`; `goal_amount <= 0` → `goal_invalid`; requiere auth (401).
- **GET:** lista incluye el default; orden por `selected_at DESC`; requiere auth.
- **PATCH:** renombra; ajusta dial; fija objetivo (deriva currency); quita objetivo (ambos null → las 3
  columnas goal NULL); objetivo a medias → `goal_invalid`; body vacío → `empty_patch`; `name` vacío →
  `name_required`; plan de otro usuario → 404; no cambia `selected_at`.
- **DELETE:** default → 409 `default_plan_undeletable`; no-default borra el plan y desaparece del `GET`; con
  `plan_movements` + sus `cash_flow_entries` + un `cash_flow_payment` planificado, todo se borra; plan de otro
  usuario → 404.
- **select:** mueve el plan al primer lugar del `GET` (`selected_at` mayor); el default es seleccionable; plan
  de otro usuario → 404; no modifica `updated_at`.

Regresión `pytest -q` verde.

---

## 10. Plan de implementación (orientativo)

Un solo slice (`feat/plans-endpoints`), 3 tasks bite-sized: (1) `POST` + `GET` (+ schemas + error codes +
helper + router registrado), (2) `PATCH` + `select`, (3) `DELETE` (orquestado).
