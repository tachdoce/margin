# financings — subdominio CRUD — Diseño

> Opciones de financiación del usuario (préstamo aprobado, promo, familiar que prestaría): **no son deudas**,
> son opciones que el `PlanEngine` consume después (a demanda) para generar planes alternativos. Subdominio
> CRUD autocontenido: tabla + 4 endpoints, **sin motor ni ciclo de revisión**.

- **Fecha:** 2026-06-09
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice: enum + tabla + modelo + migración + POST/GET/PATCH/DELETE.
- **Cierre:** rama `feat/financings`, **squash-merge** a `main`.
- **Fuente de verdad (Notion):** `BD → Flujo de dinero → financings` y
  `Endpoints → Flujo de dinero →` {POST, GET, PATCH, DELETE} `financings`.
- **Fuera de alcance:** el `PlanEngine` (consume financings, copia sus datos a `plan_movements` sin FK) y la web.

---

## 1. Enum + tabla

**Enum nativo** `financing_usage` (patrón `obligation_kind`): `primera_opcion`, `si_necesario`,
`ultimo_recurso`. Es cómo el usuario quiere que el motor combine cada opción.

**Tabla `financings`** (orden de columnas según Notion):

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `id` | uuid PK | No | |
| `user_id` | uuid FK → users | No | dueño |
| `currency_id` | smallint FK → currencies | No | 1 moneda por fila |
| `description` | varchar(100) | No | ≥ 8 chars tras trim |
| `principal_amount` | numeric(12,2) | No | > 0 |
| `start_date` | date | Sí | NULL = a demanda |
| `installment_amount` | numeric(12,2) | Sí | > 0 si no NULL |
| `installment_start_date` | date | Sí | **ancla del cronograma**; NULL = sin cronograma |
| `total_installments` | smallint | Sí | ≥ 1 si no NULL |
| `financing_rate` | numeric(5,2) | Sí | ≥ 0 si no NULL |
| `overdue_rate` | numeric(5,2) | Sí | ≥ 0 si no NULL |
| `rates_add_vat` | boolean | No | default true |
| `usage_preference` | financing_usage | No | |
| `created_at` | timestamp | No | server_default now() |
| `updated_at` | timestamp | No | server_default now(), onupdate now() |

**Relaciones:** `users 1─∞ financings`, `currencies 1─∞ financings`. **Sin** FK a `obligations`/`plans`/
`plan_movements` (el PlanEngine copia datos, no referencia). **Borrado:** hard-delete, sin cascade.

**Migración:** tabla nueva → migración aditiva normal (`alembic upgrade head`), **sin recrear** la DB. Crea el
tipo enum + la tabla. Registrar el modelo en `app/models/__init__.py`.

---

## 2. Consistencia del cronograma (regla central)

Anclada en `installment_start_date`, validada en backend (sin CHECK en BD):
- **`installment_start_date` con valor** → `installment_amount` (>0) y `total_installments` (≥1) **obligatorios**;
  `financing_rate`/`overdue_rate` opcionales (≥0 si vienen).
- **`installment_start_date` NULL** → las **4** columnas del cronograma (`installment_amount`,
  `total_installments`, `financing_rate`, `overdue_rate`) deben ser NULL. Si alguna viene con valor (incluidas
  las tasas, que sin cronograma no aplican) → 422 `installments_invalid` (**no** `rates_negative`; ese code es
  solo para tasa con valor negativo).

**POST** valida sobre el body. **PATCH** valida sobre el **estado final** (merge del body sobre la fila
existente) — así un PATCH puede **agregar** cronograma (mandando las cuotas) o **quitarlo** (mandando las 4 en
`null`).

---

## 3. Validaciones comunes

- `currency_id`: existe y pertenece al país del usuario (regla GLOBAL). Si no → 422 `currency_not_available`.
- `description`: `trim()` ≥ 8. Si no → 422 `description_invalid`.
- `principal_amount` (y `installment_amount` si viene): > 0. Si no → 422 `amount_invalid`.
- `usage_preference`: valor del enum. Si no → 422 `usage_preference_invalid`.
- `financing_rate`/`overdue_rate` (si quedan con valor): ≥ 0. Si no → 422 `rates_negative`.

> En PATCH, cada validación corre sobre el estado final (solo si el campo queda con valor). El orden de chequeo
> es el del endpoint en Notion.

---

## 4. Endpoints

| Método | Ruta | Éxito | Notas |
|---|---|---|---|
| POST | `/financings` | 201 `FinancingOut` | valida + inserta; sin motor |
| GET | `/financings` | 200 `[FinancingOut]` | del user, orden `created_at DESC`; `[]` si no hay |
| PATCH | `/financings/{id}` | 200 `FinancingOut` | 404 si no es del user; valida estado final |
| DELETE | `/financings/{id}` | 204 | 404 si no es del user; hard-delete aislado, sin 409 |

Todos: `Depends(get_current_user)`; 401 `unauthenticated` sin sesión. PATCH/DELETE: 404 `not_found` si la fila
no existe o no es del usuario.

`POST`/`PATCH` no devuelven `created_at`/`updated_at` (regla GLOBAL). `FinancingOut` = todas las columnas de
negocio: `id, currency_id, description, principal_amount, usage_preference, start_date, installment_start_date,
installment_amount, total_installments, financing_rate, overdue_rate, rates_add_vat`.

---

## 5. Schemas (`app/schemas/financing.py`)

- **`FinancingCreate`**: `currency_id`, `description`, `principal_amount`, `usage_preference` (requeridos);
  `start_date`, `installment_start_date`, `installment_amount`, `total_installments`, `financing_rate`,
  `overdue_rate` (opcionales, default None); `rates_add_vat: bool = True`.
- **`FinancingUpdate`**: todos opcionales. Se usa `model_fields_set` para distinguir "vino" de "ausente" (los
  `null` son significativos: quitar fecha/tasas). `empty_patch` si no vino ningún campo editable.
- **`FinancingOut`**: las columnas de negocio (ver §4). `from_attributes` o `from_model`.

`usage_preference` se modela como `str` en el schema y se valida contra el enum en el service (para devolver
`usage_preference_invalid` propio en vez del 422 genérico de Pydantic) — mismo criterio que otros enums del
proyecto que tienen su code propio.

---

## 6. Archivos

| Archivo | Cambio |
|---|---|
| `app/models/financing.py` | modelo `Financing` + registrar en `app/models/__init__.py` |
| `alembic/versions/<rev>_create_financings.py` | crea enum `financing_usage` + tabla |
| `app/schemas/financing.py` | Create / Update / Out |
| `app/services/financing_service.py` | `create/list/update/delete` + helper de consistencia del cronograma |
| `app/routers/financings.py` | 4 rutas; registrar en `main.py` |
| `app/core/errors.py` | + `usage_preference_invalid` |

---

## 7. Tests

Postgres `margin_test` (`create_all` + savepoint). Base: `seed_uy_currency` (Peso id 1). Usuario vía
`/auth/register`.

- **Modelo** (`tests/test_financings_model.py`): insertar con cronograma y sin cronograma; defaults
  (`rates_add_vat` true).
- **POST** (`tests/test_financings_create.py`): los 2 ejemplos (con/sin cronograma) → 201 y shape;
  `currency_not_available`; `description_invalid` (<8); `amount_invalid` (principal y cuota ≤ 0);
  `usage_preference_invalid`; `installments_invalid` (con `installment_start_date` sin `installment_amount`/
  `total_installments`; `total_installments` < 1; sin `installment_start_date` pero con alguna de las 4
  columnas); `rates_negative` (tasa < 0 con cronograma).
- **GET** (`tests/test_financings_read.py`): lista del user, orden `created_at DESC`, `[]`, no devuelve las de
  otro usuario.
- **PATCH** (`tests/test_financings_update.py`): editar `principal_amount`/`description`; **agregar** cronograma
  (estado final válido); **quitar** cronograma (4 en null); `empty_patch`; `installments_invalid` en estado
  final inconsistente; 404 ajena.
- **DELETE** (`tests/test_financings_delete.py`): 204 + fila borrada; 404 inexistente/ajena.

---

## 8. Plan de implementación (orientativo)

Un slice (`feat/financings`), TDD: modelo + migración (+ `create_all` lo toma para tests) → errores + schemas →
service (helper de cronograma + create) + POST → GET → PATCH → DELETE → registrar router → suite verde →
cierre. Notion ya documenta todo; no requiere actualización.
