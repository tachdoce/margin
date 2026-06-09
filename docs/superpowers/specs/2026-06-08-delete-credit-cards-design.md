# DELETE /credit-cards/{id} (borrado híbrido) — Diseño

> Sub-proyecto #3 de los endpoints de **credit-cards**. Borra una tarjeta; el backend elige **hard-delete**
> (sin pagos reales) o **soft-delete** (con pagos reales, preserva la historia). El *qué* está en Notion →
> Endpoints → Tarjetas de crédito → `DELETE credit-cards`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** el recurso `credit-cards` (router/service de #1–#2), `cash_flow_entries`,
  `cash_flow_payments`, las tablas definitivas del subdominio.
- **Cierre:** rama `feat/credit-cards-delete`, **squash-merge** a `main`.
- **Relacionado:** la reactivación de una tarjeta soft-deleted ocurre hoy vía `POST
  /credit-card-statements/promote` (mismo emisor+red) y, además, tendrá un endpoint propio en el
  **sub-proyecto #5** (reactivar) — a diseñar aparte.

---

## 1. Alcance

`DELETE /credit-cards/{id}` → 204. Una transacción. Decisión hard/soft según pagos reales. Sin error codes
nuevos (solo `not_found`).

**Fuera de alcance:** DELETE de statement (#4), endpoint de reactivación (#5).

---

## 2. Lógica del servicio `delete_credit_card(db, user, card_id)`

**Validación:**
1. Existe `credit_cards` con `id = {id}`, `user_id` = usuario **y** `deleted_at IS NULL` (`with_for_update`).
   Si no → 404 `not_found`. (Cubre los 3 casos sin diferenciar: no existe / de otro usuario / ya soft-deleted.)

**Decisión hard vs soft** — contar `cash_flow_payments` **reales** (`plan_id IS NULL`) sobre las
`cash_flow_entries` de la tarjeta (`source_type='tarjeta_credito'`, `source_id=card.id`):

```sql
SELECT COUNT(*)
FROM cash_flow_payments cp
JOIN cash_flow_entries cfe ON cp.cash_flow_entry_id = cfe.id
WHERE cfe.source_type = 'tarjeta_credito' AND cfe.source_id = :card_id
  AND cp.plan_id IS NULL;
```

### Caso A — count = 0 → hard-delete total

Borrado **orquestado**, en **este orden** (obligatorio por las FKs, ver §3):
1. `delete` de `cash_flow_entries` de la tarjeta (sus `cash_flow_payments` —solo planificados, no hay
   reales— se van por cascade nativo).
2. `delete` de `credit_card_purchases` de la tarjeta.
3. `delete` de `credit_card_statements` de la tarjeta (sus `credit_card_statement_items` por cascade nativo).
4. `delete` de la fila `credit_cards`.

### Caso B — count > 0 → soft-delete

1. Borrar las `cash_flow_entries` de la tarjeta **sin pago real** (id no presente en el subquery de entries
   con pago real). Sus pagos planificados, si los hubiera, se van por cascade. Las entries **con pago real
   sobreviven** apuntando a la tarjeta (historia financiera).
2. `credit_cards.deleted_at = now()`.
3. Se **conservan todos** los `credit_card_statements`, sus items y los `credit_card_purchases` (respaldo
   histórico). Ver §5 (nota de wording).

**Response:** 204 (la distinción hard/soft es transparente al cliente; el front se entera por el próximo
`GET /credit-cards`, donde una soft-deleted aparece con `is_deleted=true` y una hard-deleted ya no aparece).

---

## 3. Orden de borrado (verificado en el schema)

FKs confirmadas:
- `credit_card_statement_items → credit_card_statements`: **CASCADE** (borrar el statement borra sus items).
- `cash_flow_payments → cash_flow_entries`: **CASCADE** (borrar la entry borra sus pagos).
- `credit_card_statements → credit_cards`: **RESTRICT** (sin ondelete).
- `credit_card_purchases → credit_cards`: **RESTRICT** (sin ondelete).

Por eso, en el hard-delete, `credit_card_statements` y `credit_card_purchases` **deben** borrarse **antes** que
la fila `credit_cards` (si no, la BD rechaza el delete). `cash_flow_entries.source_id` no es FK reforzable
(polimórfica) → su borrado es orquestado por el backend (igual que el resto de la familia CashFlowEngine). Los
borrados se hacen con `delete(...)` de Core (`synchronize_session=False`); las cascades nativas hacen el resto.

---

## 4. Decisiones, con su porqué

- **Hard vs soft según pagos reales:** sin historia financiera real → limpieza total; con pagos reales →
  preservar (soft). Mismo criterio "pago real = `plan_id IS NULL`" que toda la familia CashFlowEngine.
- **Orden de borrado orquestado:** obligado por las FKs RESTRICT de statements/purchases hacia `credit_cards`
  (§3). Notion lista qué borrar; el orden lo impone el schema.
- **`source_id` polimórfica → borrado manual de entries:** no hay FK reforzable; el backend orquesta (como en
  el borrado de obligaciones/incomes).
- **404 único para los 3 casos:** para el usuario, "la tarjeta ya no está" (no se filtra mensaje).
- **El motor respeta `deleted_at`:** una soft-deleted no materializa ni reproyecta; además el motor solo se
  invoca desde promote/acknowledge/PATCH (vigentes), así que no corre sobre una soft-deleted.
- **`user_id` del token; tarjeta por pertenencia + vigente.**

---

## 5. Observaciones sobre lo documentado en Notion (no cambian el comportamiento)

- **Wording del soft-delete:** Notion dice que se conservan statements/items/purchases como "respaldo de las
  entries que **sobrevivieron**", pero en realidad se conservan **todos** — también los de períodos cuya entry
  se borró (sin pago real). El comportamiento ("conservar todo el historial") es inequívoco; solo la
  justificación está imprecisa. Implementamos "conservar todo".
- **Reactivación / purge (observación de producto, fuera de scope):** una tarjeta soft-deleted no tenía camino
  de hard-delete posterior (el DELETE da 404 si ya está borrada). Esto se aborda en parte con el endpoint de
  **reactivación (#5)**; un purge definitivo de una soft-deleted con pagos reales sigue sin existir (preservar
  historia es deliberado).

---

## 6. Tests (`tests/test_credit_cards_delete.py`)

Reusar `seed_cc_refs`/`_card_kwargs`, auth por token, sembrar tarjeta/statements/items/purchases/entries/
payments vía `db_session` para el usuario registrado. Helpers para crear una `cash_flow_entry` de la tarjeta y
un `cash_flow_payment` (real: `plan_id=None`).

- **Hard-delete (sin pagos reales):** tarjeta + statement + item + purchase + una entry sin pagos → DELETE →
  204; la tarjeta, sus statements, items, purchases y entries **desaparecen** (consultar por cada uno → vacío).
- **Hard-delete con pagos planificados:** entry con un `cash_flow_payment` `plan_id` con valor (planificado, no
  real) → cuenta como 0 reales → hard-delete; el pago planificado se va por cascade. *(opcional; requiere
  sembrar un plan)*
- **Soft-delete (con pago real):** tarjeta + entry A con pago real (`plan_id=None`) + entry B sin pago +
  statement + purchase → DELETE → 204; la tarjeta **sigue** con `deleted_at` no NULL; entry A **sobrevive**,
  entry B **se borró**; statement y purchase **se conservan**.
- **404:** tarjeta inexistente; de otro usuario; ya soft-deleted (segunda llamada al DELETE → 404).
- **401:** sin token.

> Para el conteo de pagos reales, el helper de `cash_flow_payments` setea `cash_flow_entry_id`, `amount` y
> `plan_id` (None = real). No hace falta plan para el caso soft (pago real con `plan_id=None`).

---

## 7. Plan de implementación (orientativo)

Un slice (`feat/credit-cards-delete`), TDD:
1. Servicio `delete_credit_card` + endpoint `DELETE /credit-cards/{id}` en el router; tests (rojo → verde) →
   commit.
2. Suite completa verde → cierre.
