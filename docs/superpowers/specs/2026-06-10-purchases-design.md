# purchases — registro de compras con categoría — Diseño

> El usuario registra compras del día a día (con una de sus tarjetas o en efectivo) y las clasifica con una
> categoría de gasto (Comida, Supermercado, Transporte…). Dos tablas nuevas: `purchase_categories` (catálogo
> global sembrado) y `purchases` (registro por usuario). CRUD vía `/purchases`; el catálogo se expone en
> `GET /bootstrap`. Independiente del circuito de tarjetas/statements: **no** toca `credit_card_purchases`.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice: catálogo + tabla + CRUD + bootstrap.
- **Cierre:** rama `feat/purchases`, **squash-merge** a `main`.
- **Dependencias (ya en `main`):** `credit_cards` ✓; `currencies` con `allowed_in_credit_card` ✓;
  `require_holdable_currency` en `app/services/scoping.py` ✓; `GET /bootstrap` ✓.
- **Fuera de alcance:** pantalla web; filtros/paginación en `GET /purchases`; vínculo con
  `credit_card_purchases`/statements (una compra con tarjeta acá es solo registro, no genera ítems de resumen);
  categorías por usuario (el catálogo es global y fijo); agregaciones por categoría/mes.

---

## 1. Tabla `purchase_categories` (catálogo global, se crea primero)

Sigue el patrón de `income_types`/`credit_card_item_types`: ids fijos, sembrada por migración, sin
autoincrement. Orden de presentación = `id`.

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `id` | smallint PK | No | autoincrement=False, ids fijos |
| `code` | varchar(20) | No | unique (`uq_purchase_categories_code`) |
| `name` | varchar(50) | No | texto al usuario, en español |
| `emoji` | varchar(10) | No | el front no hardcodea emojis |

**Seed (ids 1–12, orden del mockup):**

| id | code | name | emoji |
|---|---|---|---|
| 1 | `comida` | Comida | 🍔 |
| 2 | `supermercado` | Supermercado | 🛒 |
| 3 | `transporte` | Transporte | 🚌 |
| 4 | `hogar` | Hogar | 🏠 |
| 5 | `salud` | Salud | 💊 |
| 6 | `ocio` | Ocio | 🎮 |
| 7 | `ropa` | Ropa | 👕 |
| 8 | `servicios` | Servicios | 💡 |
| 9 | `suscripciones` | Suscripciones | 📺 |
| 10 | `cafe` | Café | ☕ |
| 11 | `mascotas` | Mascotas | 🐶 |
| 12 | `otros` | Otros | 🧩 |

---

## 2. Tabla `purchases` (registro por usuario)

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `id` | uuid PK | No | default uuid4 |
| `user_id` | uuid FK→users | No | dueño |
| `credit_card_id` | uuid FK→credit_cards | **Sí** | **NULL = efectivo**; si viene, tarjeta del usuario y no borrada |
| `category_id` | smallint FK→purchase_categories | **Sí** | NULL = sin clasificar |
| `description` | text | **Sí** | texto libre; se trimea, vacío se guarda como NULL |
| `purchase_date` | date | No | |
| `amount` | numeric(12,2) | No | `Decimal` en Python, > 0 |
| `currency_id` | smallint FK→currencies | No | holdable: país del usuario + `allowed_in_credit_card` |
| `created_at` | timestamptz | No | server_default now() |
| `updated_at` | timestamptz | No | server_default now() + onupdate now() |

Índice `ix_purchases_user_id_purchase_date` en (`user_id`, `purchase_date`) para el listado. **Borrado:**
hard-delete, sin `deleted_at`. Registrar el modelo en `app/models/__init__.py`. Una sola migración aditiva
crea ambas tablas y siembra el catálogo (`alembic upgrade head`), sin recrear la DB.

---

## 3. Bootstrap

`build_catalogs` (`app/services/bootstrap_service.py`) suma la clave `purchase_categories`: todas las filas
ordenadas por `id` (catálogo global, sin filtro por país ni `visible`). Sin endpoint nuevo.

---

## 4. Endpoints (`/purchases`, todos con auth)

Router finito (`app/routers/purchases.py`) → `purchase_service`. Errores con `AppError` desde el servicio.

| Endpoint | Respuesta | Descripción |
|---|---|---|
| `POST /purchases` | 201 `PurchaseOut` | crea la compra |
| `GET /purchases` | `{"purchases": [PurchaseOut]}` | las del usuario, `purchase_date` desc, `created_at` desc de desempate. Sin filtros |
| `PATCH /purchases/{purchase_id}` | `PurchaseOut` | actualización parcial |
| `DELETE /purchases/{purchase_id}` | 204 | hard-delete |

**Validaciones (POST y PATCH, mismas reglas):**

- `currency_id` → `require_holdable_currency` → `currency_not_available` (422).
- `amount` ≤ 0 → `amount_invalid` (422).
- `credit_card_id` presente y no null → debe existir, ser del usuario y tener `deleted_at` null; si no →
  `credit_card_invalid` (422, **código nuevo**: "Tarjeta no válida.").
- `category_id` presente y no null → debe existir en el catálogo; si no → `purchase_category_invalid`
  (422, **código nuevo**: "Categoría no válida.").
- `description` → trim; vacía o ausente → NULL. Sin largo mínimo.
- PATCH: parcial con `model_fields_set` (patrón de financings); sin campos → `empty_patch` (422);
  `credit_card_id: null` y `category_id: null` son valores válidos (pasa a efectivo / sin clasificar);
  los campos NOT NULL (`purchase_date`, `amount`, `currency_id`) en null explícito → `field_not_nullable` (422).
- PATCH/DELETE: la compra debe existir y ser del usuario; si no → `not_found` (404).

---

## 5. Schemas (`app/schemas/purchase.py`)

- `PurchaseCreate`: `credit_card_id: UUID | None = None`, `category_id: int | None = None`,
  `description: str | None = None`, `purchase_date: date`, `amount: Decimal`, `currency_id: int`.
- `PurchaseUpdate`: todos los campos opcionales (se distingue ausente vs null con `model_fields_set`).
- `PurchaseOut`: todas las columnas menos `user_id` (`id`, `credit_card_id`, `category_id`, `description`,
  `purchase_date`, `amount`, `currency_id`, `created_at`, `updated_at`). `amount` serializa como string
  (convención Decimal del repo). Ojo: aliasar el import de `date` (un campo `date`/`purchase_date: date`
  convive con el tipo — patrón ya conocido en el repo).

---

## 6. Service (`app/services/purchase_service.py`)

- `create_purchase(db, user, payload)` — valida todo (moneda, monto, tarjeta, categoría) antes de escribir;
  inserta y devuelve el modelo.
- `list_purchases(db, user)` — `WHERE user_id = user.id ORDER BY purchase_date DESC, created_at DESC`.
- `update_purchase(db, user, purchase_id, payload)` — busca por id + dueño (404), aplica solo
  `model_fields_set` con las mismas validaciones, devuelve el modelo.
- `delete_purchase(db, user, purchase_id)` — busca por id + dueño (404), hard-delete.

---

## 7. Archivos

| Archivo | Cambio |
|---|---|
| `app/models/purchase_category.py` | modelo `PurchaseCategory` |
| `app/models/purchase.py` | modelo `Purchase` |
| `app/models/__init__.py` | registrar ambos |
| `alembic/versions/<rev>_create_purchases.py` | crea ambas tablas + seed del catálogo |
| `app/core/errors.py` | `credit_card_invalid` y `purchase_category_invalid` |
| `app/schemas/purchase.py` | `PurchaseCreate` / `PurchaseUpdate` / `PurchaseOut` |
| `app/services/purchase_service.py` | CRUD |
| `app/services/bootstrap_service.py` | clave `purchase_categories` |
| `app/routers/purchases.py` | router + registrar en `app/main.py` |

---

## 8. Tests

Postgres `margin_test` (`create_all` + savepoint). Fixtures `db_session` + `client` + `seed_uy` existentes.

- **Catálogo** (`tests/test_bootstrap.py`): `purchase_categories` presente, 12 filas, orden por id, con emoji.
- **Modelo** (`tests/test_purchases.py`): round-trip con y sin nullables.
- **POST**: efectivo (sin `credit_card_id`); con tarjeta propia; tarjeta de otro usuario →
  `credit_card_invalid`; tarjeta borrada → `credit_card_invalid`; categoría inexistente →
  `purchase_category_invalid`; sin categoría (ok, null); moneda no holdable → `currency_not_available`;
  `amount` ≤ 0 → `amount_invalid`; `description` vacía → se guarda null.
- **GET**: solo compras del usuario autenticado; orden `purchase_date` desc.
- **PATCH**: cambia categoría; `credit_card_id: null` pasa a efectivo; body vacío → `empty_patch`;
  `purchase_date: null` → `field_not_nullable`; compra de otro usuario → 404.
- **DELETE**: 204 y desaparece; compra de otro usuario → 404.

---

## 9. Plan de implementación (orientativo)

Un slice (`feat/purchases`), TDD: modelos + migración con seed → error codes → schemas → service (validaciones
todo-antes-de-escribir) → router + main + bootstrap → suite verde → cierre (squash-merge).
