# Bootstrap (`GET /bootstrap`) — Diseño

> Primer endpoint protegido. Devuelve los catálogos maestros (el "diccionario" que el front cachea
> para mapear `id → nombre` y poblar selectores). El *qué* del producto vive en Notion → Backend →
> Endpoints → Bootstrap. Este spec consolida eso + decisiones de implementación y mis ajustes.

- **Fecha:** 2026-06-06
- **Estado:** aprobado para implementar
- **Depende de:** auth (JWT en `app/core/security.py`) y las 10 tablas de catálogo (todas en `main`).
- **Cierre:** rama `feat/bootstrap`, **squash-merge** a `main`.

---

## 1. Alcance

- **Prerrequisito:** dependencia de autenticación `get_current_user` (primer endpoint protegido del proyecto). Valida el Bearer token, carga el `User`, y es reusable por todos los endpoints protegidos futuros.
- **Endpoint:** `GET /bootstrap`, protegido, read-only. Devuelve los **8 catálogos** con campos curados, filtrados por país donde corresponde. (No incluye `countries` — ver decisiones.)
- **Fuera de alcance:** datos del usuario (`incomes`, `obligations`, `plans`, `financings`) y la línea de tiempo (`cash_flow_entries`) — se piden con su propio GET. `currency_rates` no se expone (el backend convierte y devuelve montos ya convertidos). Estrategia de invalidación de caché: diferida (hoy solo se expone el campo `version`).

---

## 2. Dependencia `get_current_user`

- Vive en `app/core/deps.py`. Usa `HTTPBearer(auto_error=False)` para extraer el token.
- Flujo: si no hay token → `AppError(unauthenticated)`; decodifica el JWT (`decode_access_token`); saca `user_id`; carga `User` por id; si no existe o `deleted_at` no es NULL → `AppError(unauthenticated)`. Devuelve el `User`.
- Cualquier fallo (sin token, token inválido/expirado, user inexistente/soft-deleted) → **401 `unauthenticated`** ("Sesión inválida o expirada."). El code ya está en el catálogo de errores.

---

## 3. Contrato

**Request:** sin body ni query params. Usuario del JWT (`Authorization: Bearer <token>`).

**Response 200** — wrapper con versión:
```json
{
  "version": "1",
  "catalogs": {
    "currencies": [ { "id": 1, "name": "Peso", "is_legal_tender": true } ],
    "obligation_types": [ { "id": 1, "obligation_kind": "gasto", "code": "alquiler", "name": "Alquiler / hipoteca", "description": "...", "default_priority_level": 2 } ],
    "income_types": [ { "id": 1, "code": "sueldo", "name": "Sueldo" } ],
    "priority_levels": [ { "level": 1, "name": "Ineludible", "description": "..." } ],
    "institutions": [ { "id": 1, "name": "BROU" } ],
    "review_finding_codes": [ { "code": "amount_above_threshold", "message": "..." } ],
    "credit_card_networks": [ { "id": 1, "code": "visa", "name": "Visa" } ],
    "credit_card_item_types": [ { "id": 1, "code": "compra", "name": "Compra", "description": "..." } ]
  }
}
```

- `version`: string de config (`bootstrap_version`, default `"1"`). Se bumpea al cambiar catálogos. Hoy es informativo (el cliente lo guarda); la invalidación real se define después.
- **Wrapper `{version, catalogs}`** en vez de catálogos en la raíz: permite agregar metadata a futuro sin romper el contrato del cliente.

**Errores:** solo `401 unauthenticated`. No tiene errores de negocio.

---

## 4. Catálogos: campos curados y filtrado

No se vuelca la fila ORM completa: cada catálogo tiene un schema Pydantic de salida con campos curados (oculta internos: `country_code`, `allowed_in_credit_card`, `visible`, timestamps).

| catálogo | campos | filtro |
|---|---|---|
| currencies | id, name, is_legal_tender | `country_code` = país del usuario |
| obligation_types | id, obligation_kind, code, name, description, default_priority_level | `visible = true` |
| income_types | id, code, name | `visible = true` |
| priority_levels | level, name, description | **todos (los 6)** |
| institutions | id, name | `visible = true` AND país del usuario |
| review_finding_codes | code, message | todos |
| credit_card_networks | id, code, name | `country_code` = país del usuario |
| credit_card_item_types | id, code, name, description | todos (catálogo global) |

**Principio rector:** el bootstrap manda **todo lo necesario para traducir/mostrar** (`id → nombre`); las reglas de **qué puede elegir** el usuario son del front. Por eso:
- `priority_levels` van **completos** (los 6): el front necesita el nivel 1 para mostrar el nombre de obligaciones que el sistema marcó como "Ineludible" (ej. `adelanto_sueldo`), aunque en el selector solo ofrezca del 2 al 6. *(Ajuste sobre Notion, que excluía el nivel 1 — excluirlo rompería el mapeo.)*
- `obligation_types` / `income_types` / `institutions` filtran por `visible`: un registro `visible = false` se discontinuó y no debe ofrecerse ni aparecer.
- `description` se incluye en `obligation_types` (texto de ayuda al elegir el tipo), además de en `priority_levels` y `credit_card_item_types`.

---

## 5. Arquitectura por capas

| archivo | responsabilidad |
|---|---|
| `app/core/deps.py` | `get_current_user` (dependency de auth reusable) |
| `app/schemas/bootstrap.py` | schema de salida por catálogo + `BootstrapResponse { version, catalogs }` |
| `app/services/bootstrap_service.py` | arma el dict de catálogos leyendo la DB, filtrado por país del usuario |
| `app/routers/bootstrap.py` | endpoint finito: `Depends(get_current_user)` → servicio → response |

El servicio no conoce HTTP; el router es finito.

---

## 6. Testing (TDD)

**`get_current_user`:**
- token válido → devuelve el `User` correcto.
- sin token → 401 `unauthenticated`.
- token inválido/mal firmado → 401 `unauthenticated`.
- usuario soft-deleted (`deleted_at` no nulo) → 401 `unauthenticated`.

**`GET /bootstrap`:**
- sin token → 401 `unauthenticated`.
- con token → 200; el body tiene `version` y `catalogs` con las **8 claves** (sin `countries`).
- `currencies` e `institutions` filtradas al país del usuario (UY); no aparece data de otro país.
- `priority_levels` trae los **6** (incluye el nivel 1).
- `obligation_types` excluye un registro `visible = false` (sembrado en el test).

Fixtures: se siembran catálogos mínimos en `margin_test` (incluido un segundo país para probar el filtrado) + un usuario UY autenticado. Reusa `client`/`db_session` del conftest.

---

## 7. Decisiones, con su porqué

- **Wrapper `{version, catalogs}`:** evita un cambio que rompa el contrato cuando se agregue metadata (cache/versión); el `version` ya deja sembrada la invalidación futura (TODO de Notion).
- **8 catálogos (incluye los de tarjeta, NO `countries`):** se suman los 2 de tarjeta (el front los necesita y evita otra llamada). Se quita `countries`: el bootstrap es post-login y el país es fijo (UY) — no se elige ni se muestra en la app, así que `countries` no tiene consumidor. Un futuro selector de país viviría en el registro (pre-login, endpoint público aparte). *(Ajuste sobre Notion, que listaba 7 incluyendo countries.)*
- **`priority_levels` completos:** el bootstrap es un diccionario de traducción; excluir el nivel 1 rompería mostrar items de ese nivel. La restricción de selección es del front.
- **Campos curados con schemas Pydantic:** contrato estable, no se filtran columnas internas.
- **`get_current_user` reusable:** primer endpoint protegido; la dependencia sirve para todos los futuros.
