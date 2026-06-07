# `GET` + `DELETE` + `reactivate` /incomes (slice 3 de Ingresos) — Diseño

> Tercer y último slice de la primera tanda de Ingresos: listar, borrar (soft, provisorio) y reactivar
> fuentes de ingreso. El *qué* del producto vive en Notion → Endpoints → Ingresos → GET / DELETE /
> POST reactivate.

- **Fecha:** 2026-06-07
- **Estado:** aprobado para implementar
- **Depende de:** tabla `incomes` + `POST`/`PATCH` (slices 1 y 2, en `main`), `get_current_user`.
- **Cierre:** rama `feat/incomes-get-delete-reactivate`, **squash-merge** a `main`.

---

## 1. Alcance

Tres endpoints, todos `Depends(get_current_user)`, que se suman a `app/routers/incomes.py` y
`app/services/income_service.py` (ya existentes del slice 2):

- **`GET /incomes`** (200): lista **todas** las fuentes del usuario (vigentes + borradas), con `is_deleted`.
- **`DELETE /incomes/{id}`** (204): **soft-delete provisorio** — setea `deleted_at` siempre.
- **`POST /incomes/{id}/reactivate`** (200): limpia `deleted_at`, devuelve el income.

**Decisión clave (no-Notion, provisoria):** el `DELETE` es **soft incondicional**. Notion define un DELETE
híbrido (hard-delete si no hay pagos reales; soft-delete si los hay) + cascada de `cash_flow_entries`. Esa
lógica depende de tablas `cash_flow_*` que no existen. Hacemos soft incondicional para que `reactivate`
tenga sentido y los 3 endpoints sean testeables hoy. El `DELETE` real **reemplaza** al provisorio cuando
exista el CashFlowEngine.

**Diferido:** el DELETE híbrido + cascada, y la re-materialización de `cash_flow_entries` en delete/reactivate.

---

## 2. Contrato

### GET /incomes
Sin query params. Devuelve las fuentes del **usuario del token**, vigentes y soft-deleted, ordenadas por
`created_at DESC`. Cada una con `is_deleted` derivado (el front filtra: lista activa = `false`, vista de
reactivación = `true`).

**200:**
```json
{ "incomes": [ { "...campos de IncomeOut...", "is_deleted": false } ] }
```
Sin ingresos → `{ "incomes": [] }`. Error: 401 `unauthenticated`.

### DELETE /incomes/{id}
Soft-delete provisorio. Busca por `id` + `user_id` (del token) + `deleted_at IS NULL`; si no existe → **404
`not_found`** (cubre inexistente / ajeno / ya borrado, sin diferenciar). Si existe: `deleted_at = now()`,
`updated_at = now()`.

**204** sin body. Errores: 401, 404 `not_found`.

### POST /incomes/{id}/reactivate
Busca por `id` + `user_id` **sin** filtrar por `deleted_at` (buscamos una borrada). Si no existe / ajeno →
**404 `not_found`**. Si la fila tiene `deleted_at IS NULL` (ya vigente) → **409 `income_not_deleted`**
("Este ingreso no está borrado."). Si OK: `deleted_at = NULL`, `updated_at = now()`.

**200:** `IncomeOut` con `is_deleted = false`. Errores: 401, 404 `not_found`, 409 `income_not_deleted`.

---

## 3. Schemas (`app/schemas/income.py`)

- Sumar **`IncomeListOut`**: `{ incomes: list[IncomeOut] }`.
- `reactivate` reusa `IncomeOut` (con `from_model`, que deriva `is_deleted`). `IncomeCreate/Update/Out` ya existen.

---

## 4. Servicio (`app/services/income_service.py`) — 3 funciones nuevas

- `list_incomes(db, user) -> list[Income]`:
  `db.execute(select(Income).where(Income.user_id == user.id).order_by(Income.created_at.desc())).scalars().all()`.
- `delete_income(db, user, income_id) -> None`: busca con `id` + `user_id` + `deleted_at IS NULL`; si no →
  `AppError(not_found)`; setea `income.deleted_at = func.now()` (o `datetime.now(timezone.utc)`); `commit`.
- `reactivate_income(db, user, income_id) -> Income`: busca con `id` + `user_id` (sin filtro de `deleted_at`);
  si no → `AppError(not_found)`; si `income.deleted_at is None` → `AppError(income_not_deleted)`; setea
  `income.deleted_at = None`; `commit`; `refresh`; devuelve.

El servicio no conoce HTTP; lanza `AppError`. El router es finito.

---

## 5. Router (`app/routers/incomes.py`) — 3 endpoints nuevos

- `GET /incomes` → 200, `response_model=IncomeListOut`; devuelve
  `IncomeListOut(incomes=[IncomeOut.from_model(i) for i in income_service.list_incomes(db, user)])`.
- `DELETE /incomes/{income_id}` → `status_code=204`; llama `income_service.delete_income(...)`; sin retorno.
- `POST /incomes/{income_id}/reactivate` → 200, `response_model=IncomeOut`; devuelve
  `IncomeOut.from_model(income_service.reactivate_income(...))`.

El router ya está montado en `main.py` (slice 2). `income_id: uuid.UUID` como path param (ya se usa en PATCH).

---

## 6. Error code nuevo (`ErrorCode` en `app/core/errors.py`)

`income_not_deleted = (409, "Este ingreso no está borrado.")`.

---

## 7. Testing (extiende `tests/test_incomes.py`)

Reusa los helpers existentes (`_seed_refs`, `_auth(client, email=...)`, `_recurring_body`, `_create_recurring`).

**GET:**
- sin ingresos → `{ "incomes": [] }`.
- con varias → vienen ordenadas por `created_at DESC` (la última creada primero).
- incluye una soft-deleted con `is_deleted = true` (se crea una, se borra, sigue apareciendo en GET).
- aislamiento por usuario: un segundo usuario no ve los ingresos del primero.
- sin token → 401.

**DELETE:**
- borra (204) y luego aparece en GET con `is_deleted = true`.
- segundo DELETE al mismo id → 404 (ya borrada, `deleted_at` no NULL).
- income ajeno → 404.
- inexistente → 404.
- sin token → 401.

**reactivate:**
- sobre una borrada → 200, `is_deleted = false`, y en GET vuelve como vigente.
- sobre una vigente → 409 `income_not_deleted`.
- ajena / inexistente → 404.
- sin token → 401.

---

## 8. Decisiones, con su porqué

- **DELETE soft incondicional (provisorio):** habilita `reactivate` y un conjunto testeable hoy; se
  reemplaza por el híbrido real con el CashFlowEngine. La fila no se borra físicamente nunca en este slice.
- **DELETE → 204 sin body:** idiomático para un comando de borrado, y **estable a futuro**: el DELETE real
  a veces hace hard-delete (la fila desaparece) y no podría devolver el recurso; comprometerse con 204 ahora
  evita romper el contrato después. `reactivate` sí devuelve body porque es una acción que produce estado.
- **404 que no diferencia (inexistente / ajeno / ya borrado):** para el usuario el income "ya no está"; no
  filtramos información de existencia de recursos ajenos.
- **GET sin paginación ni filtros:** YAGNI; el front filtra por `is_deleted` del lado del cliente. Se suma
  server-side si el volumen lo justifica.
