# PATCH + acknowledge /credit-cards/{id} — Diseño

> Sub-proyecto #2 de los endpoints de **credit-cards**. Las dos mutaciones de una tarjeta ya promovida que
> cierran su ciclo de revisión y disparan el motor: editar (`PATCH`) y reconocer findings (`acknowledge`). El
> *qué* está en Notion → Endpoints → Tarjetas de crédito → `PATCH credit-cards`, `POST credit-cards
> acknowledge`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** el recurso `credit-cards` (router/service/schema de la #1, reusa `CreditCardOut`), los
  reviewers/motor (`review_credit_card`, `materialize_credit_card`), catálogos.
- **Cierre:** rama `feat/credit-cards-patch-ack`, **squash-merge** a `main`.

---

## 1. Alcance

Agregar al recurso:
- `PATCH /credit-cards/{id}` — edición parcial (3 campos) → reviewer → motor.
- `POST /credit-cards/{id}/acknowledge` — limpia findings, `is_ready=true` → motor.

**Fuera de alcance:** DELETE de tarjeta (#3) y DELETE de statement (#4).

---

## 2. Error codes nuevos (`app/core/errors.py`)

| code | status | mensaje |
|---|---|---|
| `closing_day_invalid` | 422 | `El día de cierre debe estar entre 1 y 31.` |
| `card_already_exists` | 409 | `Ya tenés una tarjeta con ese emisor y esa red.` |
| `card_has_no_findings` | 409 | `La tarjeta no tiene observaciones para reconocer.` |

Reusados: `not_found` (404), `empty_patch` (422), `institution_invalid` (422), `card_network_invalid` (422).

---

## 3. PATCH /credit-cards/{id}

**Request `CreditCardUpdate`** — los 3 editables, opcionales:

```python
class CreditCardUpdate(BaseModel):
    institution_id: int | None = None
    card_network_id: int | None = None
    closing_day: int | None = None
```

**Servicio `update_credit_card(db, user, card_id, payload) -> CreditCard`. Validaciones en orden:**
1. La tarjeta `{id}` existe, es del usuario y **vigente** (`deleted_at IS NULL`). Si no → 404 `not_found`.
   (Una soft-deleted no se edita; se reactiva promoviendo.)
2. El body trae al menos uno de los 3. Si los tres son None → 422 `empty_patch`.
3. Si vino `institution_id`: existe + país del usuario → si no, 422 `institution_invalid`.
4. Si vino `card_network_id`: existe + país del usuario → si no, 422 `card_network_invalid`.
5. Si vino `closing_day`: 1 ≤ valor ≤ 31 → si no, 422 `closing_day_invalid`.
6. **Unicidad:** si cambió `institution_id` o `card_network_id`, la combinación final (nuevos + los que no
   cambiaron) no debe existir en **otra** `credit_cards` **vigente** del usuario (`id != card.id`,
   `deleted_at IS NULL`). Si existe → 409 `card_already_exists`.

**Update + ciclo.** Reemplazar solo los campos provistos (`updated_at = now()` por `onupdate`, es un cambio de
negocio real). Correr `review_credit_card(db, card.id)` (reabre el ciclo; como la tarjeta es existente —
`created_at != updated_at` tras el edit— evalúa `closing_day_changed`). Luego `materialize_credit_card(db,
card.id)`. `commit` + `refresh`.

**Response 200 `CreditCardOut`.**

---

## 4. POST /credit-cards/{id}/acknowledge

Body vacío (`{}`).

**Servicio `acknowledge_credit_card(db, user, card_id) -> CreditCard`. Validaciones en orden:**
1. La tarjeta `{id}` existe, es del usuario y **vigente**. Si no → 404 `not_found`.
2. `card.review_findings != '[]'`. Si está vacío → 409 `card_has_no_findings`.

**Update.** `review_findings='[]'`, `user_acknowledged_at=now`, `is_ready=true`. **No** se re-corre el reviewer.

**`updated_at` (decisión del usuario):**
- Si `card.created_at == card.updated_at` (tarjeta **nueva** recién creada) → `updated_at = now()`: la tarjeta
  **deja de ser nueva**, para que el reviewer no la vuelva a tratar como creación (no re-emita
  `closing_day_inferred`) si corre de nuevo.
- Si `created_at != updated_at` (tarjeta existente, p.ej. aceptando `closing_day_changed`) → se **preserva**
  `updated_at` (reconocer no es cambio de negocio — Regla de updated_at).

Se implementa con un `update(CreditCard).values(..., updated_at=<elegido>)` de Core (evita que el
`onupdate=now()` decida por su cuenta).

**Motor.** Tras el update, `materialize_credit_card(db, card.id)` — el motor ve `is_ready=true` y **materializa**
(a diferencia del acknowledge de staging, que no dispara motor). `commit` + `refresh`.

**Response 200 `CreditCardOut`.**

---

## 5. Decisiones, con su porqué

- **PATCH solo 3 campos:** límite/tasas/`rates_add_vat` se actualizan al promover, no por edición manual
  (criterio de Notion).
- **Unicidad explícita además del índice parcial:** da el 409 amigable `card_already_exists` antes de chocar
  el `UNIQUE (user_id, institution_id, card_network_id) WHERE deleted_at IS NULL`; el chequeo es contra
  vigentes y excluye la propia tarjeta.
- **`updated_at` condicional en acknowledge (decisión del usuario):** reconocer una tarjeta nueva la
  **gradúa** de "nueva" (bump de `updated_at`); reconocer una existente preserva `updated_at`. Mantiene
  confiable el criterio `created_at == updated_at` del `ReviewEngine.credit_cards`.
- **acknowledge SÍ dispara el motor (a diferencia del de staging):** la tarjeta materializa; el de staging no
  (la madre no materializa). El gate `is_ready=true` recién habilitado deja al motor materializar.
- **PATCH reabre el ciclo vía el reviewer + motor:** mismo pipeline que el resto (reviewer → CashFlowEngine en
  la misma transacción; rollback si el motor falla).
- **Reuso de `CreditCardOut`:** incluye `is_deleted` (siempre `false` acá, la tarjeta es vigente). Notion no lo
  dibuja en estos 2 ejemplos; se incluye por consistencia de schema. Al cerrar, se refleja en esas 2 páginas
  de Notion (junto con el `is_deleted`).
- **`user_id` del token; tarjeta por pertenencia + vigente.**

---

## 6. Tests (extender `tests/test_credit_cards_read.py` o nuevo `tests/test_credit_cards_mutations.py`)

Usar un archivo nuevo `tests/test_credit_cards_mutations.py`. Reusar `seed_cc_refs`/`_card_kwargs`, auth por
token, sembrar la tarjeta vía `db_session` para el usuario registrado. Para el caso de unicidad sembrar una
segunda institución/red.

**PATCH:**
- **200 edita closing_day:** `{"closing_day": 15}` → 200, `closing_day` 15; corre reviewer (con un statement
  cercano, `is_ready` true; sin statement, rama existente sin `closing_day_changed` → `[]`).
- **404:** tarjeta inexistente / de otro usuario / soft-deleted.
- **422 `empty_patch`:** body `{}`.
- **422 `institution_invalid`:** `institution_id` inexistente/otro país.
- **422 `card_network_invalid`:** `card_network_id` inexistente.
- **422 `closing_day_invalid`:** `closing_day` 0 o 32.
- **409 `card_already_exists`:** existe otra tarjeta vigente del usuario con el `(institution_id,
  card_network_id)` final.
- **`closing_day_changed` al editar:** tarjeta con un statement día 13; PATCH `closing_day=25` (dif 12) →
  `review_findings == ["closing_day_changed"]`, `is_ready false`.

**acknowledge:**
- **200 tarjeta nueva:** `review_findings=["closing_day_inferred"]`, `is_ready=false`, `created_at==updated_at`
  → acknowledge → `review_findings []`, `is_ready true`; y `updated_at` quedó **distinto** de `created_at` (se
  graduó). El motor materializó (hay `cash_flow_entries` si tiene statement con totales > 0).
- **200 tarjeta existente:** `created_at != updated_at`, con findings → acknowledge → `updated_at` se
  **preserva**.
- **404:** inexistente / otro usuario / soft-deleted.
- **409 `card_has_no_findings`:** tarjeta con `review_findings='[]'`.
- **401** en ambos.

> Para verificar el motor: sembrar la tarjeta con un `credit_card_statements` de totales > 0 + la moneda USD
> (Dólar id 3) si se chequean entries; o solo verificar `is_ready`/`review_findings` si no se mira el motor.

---

## 7. Plan de implementación (orientativo)

Un slice (`feat/credit-cards-patch-ack`), TDD:
1. 3 codes en `errors.py`; schema `CreditCardUpdate`.
2. Tests (rojo) → servicio (`update_credit_card`, `acknowledge_credit_card`) + 2 endpoints en el router
   (verde) → commit.
3. Suite completa verde → cierre. Post-cierre: reflejar en las 2 páginas de Notion (PATCH/ack) el envoltorio
   de respuesta no aplica (son objetos, no listas) — solo agregar `is_deleted` al ejemplo si se decide.
