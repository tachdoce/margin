# POST /credit-cards/{id}/reactivate — Diseño

> Sub-proyecto #5 de los endpoints de **credit-cards**. **Endpoint nuevo, no documentado en Notion** — surge
> de la duda de producto del DELETE (#3): una tarjeta soft-deleted solo "volvía" promoviendo un resumen; este
> endpoint da una vía explícita para reactivarla. Al cerrar el sub-proyecto se **crea la página en Notion**
> espejando el formato de los demás.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** el recurso `credit-cards` (router/service, `CreditCardOut`), `review_credit_card`,
  `materialize_credit_card`.
- **Cierre:** rama `feat/credit-cards-reactivate`, **squash-merge** a `main`. Post-cierre: crear la página de
  Notion del endpoint.

---

## 1. Alcance

`POST /credit-cards/{id}/reactivate` → 200 `CreditCardOut`. Una transacción. Limpia `deleted_at`, recalcula el
ciclo (reviewer) y reconstruye las proyecciones (motor).

**Contexto:** el soft-delete (#3) deja la tarjeta con `deleted_at` y borra sus `cash_flow_entries` futuras sin
pago real (las con pago real sobreviven). Reactivar la vuelve vigente y restaura las proyecciones.

---

## 2. Error code nuevo (`app/core/errors.py`)

| code | status | mensaje |
|---|---|---|
| `card_not_deleted` | 409 | `La tarjeta no está borrada.` |

Reusados: `not_found` (404), `card_already_exists` (409).

---

## 3. Lógica del servicio `reactivate_credit_card(db, user, card_id)`

**Validaciones (en orden):**
1. La tarjeta `{id}` existe y es del usuario (`with_for_update`). Si no → 404 `not_found`.
2. Está **soft-deleted** (`deleted_at IS NOT NULL`). Si está vigente → 409 `card_not_deleted` (no hay nada que
   reactivar).
3. **Sin conflicto de unicidad:** no existe **otra** `credit_cards` **vigente** (`deleted_at IS NULL`) del
   usuario con el mismo `(institution_id, card_network_id)` (`id != card.id`). Si existe → 409
   `card_already_exists` (reactivar dejaría dos vigentes con esa combinación, violando el índice único
   parcial; el usuario debe resolver eso primero).

**Reactivación + pipeline:**
4. `card.deleted_at = None` → `flush` (el `onupdate` bumpea `updated_at`, así `created_at != updated_at` y el
   reviewer no la trata como nueva).
5. `review_credit_card(db, card.id)` — reabre el ciclo; como es existente, evalúa `closing_day_changed` contra
   el último resumen y deja `is_ready`/`review_findings` al día.
6. `materialize_credit_card(db, card.id)` — el motor valida `is_ready` internamente: si quedó lista,
   reproyecta desde el último resumen (restaura las futuras borradas en el soft-delete); si quedó con findings,
   no-op hasta que el usuario acepte/corrija. Si el motor lanza, rollback total. `commit` + `refresh`.

**Response 200 `CreditCardOut`** (la tarjeta reactivada; `is_deleted=false`).

---

## 4. Decisiones, con su porqué

- **Pipeline reviewer → motor (como PATCH/promote):** reactivar recalcula el ciclo antes de materializar, así
  `is_ready` refleja el estado actual (p.ej. un `closing_day_changed` vigente vuelve a frenar la
  materialización hasta que el usuario lo resuelva). Consistente con el resto del subdominio.
- **No es "nueva":** al limpiar `deleted_at` el `onupdate` bumpea `updated_at`; la tarjeta ya tenía
  `created_at != updated_at` (fue promovida antes), así que el reviewer toma la rama existente
  (`closing_day_changed`), no `closing_day_inferred`.
- **Conflicto de combinación → 409, no merge:** el índice único parcial solo admite una vigente por
  `(user, emisor, red)`; si ya hay una vigente, reactivar no puede dejar dos. El usuario resuelve primero.
- **Restaura proyecciones vía el motor:** es el valor del endpoint — el soft-delete había borrado las futuras
  sin pago real; el motor las reconstruye.
- **`user_id` del token; tarjeta por pertenencia.**

---

## 5. Tests (`tests/test_credit_cards_reactivate.py`)

Reusar `_auth`/`_last_user`/`_make_card`/`_make_statement` (de `test_credit_cards_read`). Fixture local con
USD (Dólar 3) que el motor necesita. Helpers de entry/payment si se chequea materialización.

- **200 reactiva:** tarjeta soft-deleted (`deleted_at` con valor), `is_ready=True`, `created_at != updated_at`,
  con un statement → POST reactivate → 200; `is_deleted=false`; la tarjeta queda vigente
  (`deleted_at IS NULL`). (El motor corre sin romper.)
- **Reactivada materializa:** soft-deleted con un statement de totales > 0 → tras reactivar hay
  `cash_flow_entries` del período (el motor reproyectó).
- **404:** tarjeta inexistente / de otro usuario.
- **409 `card_not_deleted`:** tarjeta **vigente** (`deleted_at IS NULL`) → 409.
- **409 `card_already_exists`:** existe otra tarjeta vigente del usuario con el mismo `(institution_id,
  card_network_id)` → 409; la soft-deleted sigue soft-deleted.
- **`closing_day_changed` al reactivar:** soft-deleted `closing_day=13` con último statement día 25 → tras
  reactivar, `review_findings == ["closing_day_changed"]`, `is_ready=false` (y el motor no materializó).
- **401** sin token.

> Para las tarjetas soft-deleted "existentes" usar `created_at` explícito anterior + `deleted_at` con valor
> (dentro de una transacción `now()` es fijo). Capturar ids antes si se borrara algo (acá no se borra, pero el
> commit expira objetos: releer vía `db_session` por id).

---

## 6. Plan de implementación (orientativo)

Un slice (`feat/credit-cards-reactivate`), TDD:
1. Code `card_not_deleted`; servicio `reactivate_credit_card` + endpoint `POST /credit-cards/{id}/reactivate`;
   tests (rojo → verde) → commit.
2. Suite completa verde → cierre.
3. Post-cierre: crear la página de Notion del endpoint.
