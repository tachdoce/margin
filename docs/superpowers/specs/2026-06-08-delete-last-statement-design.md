# DELETE /credit-cards/{id}/statements (deshacer última promoción) — Diseño

> Sub-proyecto #4 de los endpoints de **credit-cards**. Borra el **último** estado de cuenta promovido de una
> tarjeta (deshacer una promoción equivocada), con sus items, y dispara el motor para reproyectar desde el
> nuevo último. El *qué* está en Notion → Endpoints → Tarjetas de crédito → `DELETE credit-cards-statements`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** el recurso `credit-cards` (router/service), `credit_card_statements`/items,
  `cash_flow_entries`/`cash_flow_payments`, `materialize_credit_card`.
- **Cierre:** rama `feat/credit-cards-delete-statement`, **squash-merge** a `main`.

---

## 1. Alcance

`DELETE /credit-cards/{id}/statements` → 204. Una transacción. Borra siempre el resumen más reciente de la
tarjeta; rechaza si ese período tiene pagos reales; reproyecta vía el motor.

**Fuera de alcance:** endpoint de reactivación (#5).

---

## 2. Error code nuevo (`app/core/errors.py`)

| code | status | mensaje |
|---|---|---|
| `statement_has_payments` | 409 | `No se puede borrar un resumen que ya tiene pagos registrados.` |

Reusado: `not_found` (404).

---

## 3. Lógica del servicio `delete_last_statement(db, user, card_id)`

**Validaciones (en orden):**
1. La tarjeta `{id}` existe y es del usuario (`with_for_update`). **No** se filtra por `deleted_at` (una
   soft-deleted igual puede deshacer su último resumen). Si no → 404 `not_found`.
2. El `credit_card_statements` más reciente de la tarjeta (mayor `issue_year`, luego `issue_month`). Si la
   tarjeta no tiene ninguno → 404 `not_found`.
3. **Chequeo de pagos:** contar `cash_flow_payments` reales (`plan_id IS NULL`) sobre la `cash_flow_entries`
   de ese período (`source_type='tarjeta_credito'`, `source_id=card.id`, `issue_year`, `issue_month` del
   statement). Si ≥ 1 → 409 `statement_has_payments`. El endpoint frena acá, antes de tocar nada.

**Borrado:**
- `db.delete(statement)` (sus `credit_card_statement_items` por `ON DELETE CASCADE`).
- **No** se toca `credit_card_purchases` (dato de autocompletado; revertir su `last_statement_closing_date`
  no es posible —no se guarda el previo— y un valor "adelantado" no rompe nada).

**Reproyección:** `materialize_credit_card(db, card.id)` en la misma transacción. El motor relee: R1 toma el
**nuevo último** statement (el anterior, ya consistente; el UPSERT lo encuentra por clave) y R2 reproyecta los
meses siguientes, reconciliando por clave lógica las proyecciones que había dejado el resumen borrado (las
pisa o borra). Si el motor tuviera que pisar una entry con pago real lanza excepción y rollback (salvaguarda
última, ya cubierta por el paso 3). Si el motor lanza, rollback total. `commit`.

**Response:** 204.

---

## 4. Decisiones, con su porqué

- **Solo el último (no recibe statement id):** deshacer es siempre desde la punta, para no dejar huecos en el
  historial. El backend resuelve el más reciente por `(issue_year, issue_month)`.
- **Chequeo de pagos en el endpoint (no delegado al motor):** borrar un período con pago real descolocaría un
  hecho económico; el 409 es la vía de error al usuario. El motor queda como salvaguarda última.
- **No se tocan los purchases:** son autocompletado; revertir limpio no es posible y un dato adelantado no
  afecta el flujo.
- **El borrado del último SÍ dispara el motor** (a diferencia de un borrado genérico): el "nuevo último" es el
  anterior, ya consistente, así que la reproyección es limpia. El motor valida `is_ready` internamente.
- **Sin filtro `deleted_at` en la tarjeta:** una soft-deleted puede deshacer su último resumen igual.
- **`user_id` del token; tarjeta por pertenencia.**

---

## 5. Tests (`tests/test_credit_cards_delete_statement.py`)

Reusar `_auth`/`_last_user`/`_make_card`/`_make_statement` (de `test_credit_cards_read`). Fixture local que
extiende `seed_cc_refs` con la moneda USD (Dólar id 3) que el motor necesita al materializar. La tarjeta se
siembra con `is_ready=True` para que el motor corra. Helpers para `cash_flow_entry` + `cash_flow_payment`.

- **204 borra el último + items, motor reproyecta:** tarjeta `is_ready=True` con dos statements (2026/04 y
  2026/05) y los items de mayo → DELETE → 204; el statement de mayo y sus items **desaparecen**, el de abril
  **queda**; el motor corrió sin romper (204).
- **404 sin resúmenes:** tarjeta sin statements → 404.
- **404 tarjeta inexistente / de otro usuario.**
- **409 `statement_has_payments`:** el período del último statement tiene una `cash_flow_entry` con un
  `cash_flow_payment` real (`plan_id=None`) → 409; el statement **no** se borra.
- **401** sin token.

> Capturar los ids necesarios (statement, items) **antes** del DELETE: el `commit` del servicio expira los
> objetos de la sesión compartida y leer `.id` de uno borrado falla (mismo patrón que en los tests de DELETE
> de tarjeta).

---

## 6. Plan de implementación (orientativo)

Un slice (`feat/credit-cards-delete-statement`), TDD:
1. Code `statement_has_payments`; servicio `delete_last_statement` + endpoint `DELETE
   /credit-cards/{id}/statements`; tests (rojo → verde) → commit.
2. Suite completa verde → cierre.
