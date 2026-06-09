# POST /credit-card-statements/promote — Diseño

> Sub-proyecto del subdominio **Tarjetas de crédito** (capa de endpoints). El endpoint central: promueve el
> staging del usuario a las tablas definitivas (`credit_cards` + `credit_card_statements` + items + purchases),
> corre el reviewer de la tarjeta y el `CashFlowEngine.credit_cards`, y borra el staging. Cierra el flujo de
> carga end-to-end. El *qué* está en Notion → Endpoints → Tarjetas de crédito →
> `POST staging-credit-card-statements promote`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** todo el dominio de tarjetas ya construido (tablas, reviewers, motor) y el recurso de staging
  (POST/PUT/GET/DELETE/acknowledge). Reusa `review_credit_card`, `materialize_credit_card`.
- **Cierre:** rama `feat/promote-credit-card-statements`, **squash-merge** a `main`.

---

## 1. Alcance

`POST /credit-card-statements/promote` (un slice, todo junto): validaciones → traspaso (5 pasos) → borrar
staging, en **una transacción**. Sin id en la ruta (staging del token).

**Fuera de alcance:** endpoints de `credit-cards` (GET/PATCH/DELETE/acknowledge), GET de historial.

---

## 2. Error codes nuevos (`app/core/errors.py`) — todos 409

| code | mensaje |
|---|---|
| `statement_not_ready` | `El resumen tiene observaciones sin resolver.` |
| `items_incomplete` | `Hay ítems del resumen sin completar.` |
| `rates_required_new_card` | `Para dar de alta una tarjeta nueva, completá las tasas y el dato de IVA.` |
| `statement_period_exists` | `Ya cargaste un resumen de ese mes para esta tarjeta.` |
| `statement_period_not_after_last` | `Tenés que cargar el resumen siguiente al último que ya cargaste.` |

Reusado: `not_found` (404).

---

## 3. Validaciones (en orden)

1. El usuario tiene staging (`staging_credit_cards` por `user_id`, `with_for_update`). Si no → 404 `not_found`.
2. **Madre lista + completa.** `madre.is_ready` debe ser `true`; además (guarda defensiva, ver §6) los 10
   campos obligatorios de la madre no-NULL (`institution_id`, `card_network_id`, `closing_date`, `due_date`,
   `current_limit`, `total_local`, `total_usd`, `minimum_payment_local`, `minimum_payment_usd`,
   `rates_add_vat`). Si no → 409 `statement_not_ready`.
3. **Ítems completos.** Cada `staging_credit_card_items`: `charge_date`, `description`, `amount`,
   `currency_id`, `item_type_id` no-NULL y cuotas consistentes (ambas NULL, o ambas con valor con
   `current_installment >= 1`, `total_installments >= 1`, `current_installment <= total_installments`). Si
   alguno falla → 409 `items_incomplete`.
4. **Tarjeta nueva → tasas obligatorias.** Buscar `credit_cards` del usuario para `(institution_id,
   card_network_id)` — vigente **o** soft-deleted (§5.1). Si **no existe** ninguna, las 4 tasas + `rates_add_vat`
   del staging deben estar todas presentes; si falta alguna → 409 `rates_required_new_card`.
5. **Período no duplicado.** Solo si la tarjeta ya existe: `(issue_year, issue_month)` (del `closing_date`)
   contra los `credit_card_statements` de la tarjeta; si ya hay uno igual → 409 `statement_period_exists`.
6. **Período posterior al último.** Solo si la tarjeta ya existe: tomar el statement de mayor
   `(issue_year, issue_month)`; si el período del staging **no es estrictamente posterior** → 409
   `statement_period_not_after_last`. (Comparación por tupla `(año, mes)`, no por día.) El paso 5 gana ante un
   igual; este cubre los anteriores.

---

## 4. Traspaso (una transacción)

`issue_year`/`issue_month` = `madre.closing_date.year` / `.month`.

### Paso 1 — UPSERT `credit_cards`

Resolver la tarjeta existente (§5.1): primero la **vigente** (`deleted_at IS NULL`); si no hay, una
**soft-deleted**. `is_new = no hay ninguna`.

- **Nueva:** crear con `current_limit`, las 4 tasas y `rates_add_vat` del staging, `closing_day =
  closing_date.day`, ciclo inicial (`reviewed_at=None`, `review_findings='[]'`, `user_acknowledged_at=None`,
  `is_ready=False`).
- **Existente (vigente o soft-deleted):** `deleted_at = None` (reactiva si estaba borrada), `current_limit`
  del staging, y cada tasa/`rates_add_vat` **solo si vino no-NULL** (NULL conserva el valor vigente).
  `closing_day` y las columnas del ciclo **no se tocan**.

### Paso 2 — INSERT `credit_card_statements`

Una fila colgando de la tarjeta: `issue_year`/`issue_month`, `closing_date`, `due_date`, totales y mínimos del
staging.

### Paso 3 — INSERT `credit_card_statement_items`

Copia directa de cada `staging_credit_card_items` (ya validados completos) colgando del statement del paso 2.

### Paso 4 — UPSERT `credit_card_purchases`

Por cada ítem que **califica**:
- **Con cuotas** (`total_installments` no-NULL): buscar por `(credit_card_id, charge_date, description,
  total_installments)`; si existe → actualizar `last_statement_closing_date = madre.closing_date`,
  `item_type_id` (por si reclasificó) y `updated_at`; si no → crear.
- **Sin cuotas y `item_type` = `suscripcion`**: **crear siempre** una fila nueva (su `charge_date` cambia cada
  mes, nunca matchea).
- **Sin cuotas y no suscripción**: se omite.

Al crear: `credit_card_id`, `description`, `charge_date` (tal cual), `amount`, `currency_id`,
`total_installments` (NULL si suscripción), `item_type_id`, `last_statement_closing_date = madre.closing_date`.

### Reviewer + Paso 5 (motor)

Tras los pasos 1–4, en la misma transacción:
- `review_credit_card(db, card.id)` — **siempre** (decisión §6). Nueva → `closing_day_inferred`
  (`is_ready=false`); existente → evalúa `closing_day_changed` contra el statement recién insertado.
- `materialize_credit_card(db, card.id)` — el motor valida `is_ready` internamente (nueva o con
  `closing_day_changed` → no-op; lista → materializa + proyecta).

### Cierre

`db.delete(madre)` (ítems por `ON DELETE CASCADE`). `commit`. El usuario queda sin staging.

---

## 5. Detalles

### 5.1 Resolver la tarjeta existente

El índice único parcial solo garantiza una **vigente** por `(user, emisor, red)`; pueden coexistir una vigente
y soft-deleted previas. Por eso: buscar primero la vigente (`deleted_at IS NULL`); si no hay, una soft-deleted
(`order by deleted_at desc, limit 1`). Así nunca se reactiva una soft-deleted habiendo una vigente (evita dos
vigentes y la violación del índice).

### 5.2 Subtipo `suscripcion`

Se resuelve una vez por corrida: `credit_card_item_types.id` con `code = 'suscripcion'`.

---

## 6. Decisiones, con su porqué

- **Reviewer siempre en el promote (resuelve contradicción de Notion):** la página del promote dice "no
  re-dispara el reviewer en tarjeta existente", pero la regla `closing_day_changed` del
  `ReviewEngine.credit_cards` compara el **último resumen** (que el promote acaba de insertar) contra
  `closing_day` — sin correr el reviewer, esa regla sería código muerto. Se corre `review_credit_card` después
  del Paso 2 en todos los casos (decisión del usuario). El reviewer se apoya en `created_at == updated_at`:
  nueva → iguales (misma transacción) → `closing_day_inferred`; existente → el UPDATE del Paso 1 bumpea
  `updated_at` → difieren → rama `closing_day_changed`.
- **Guarda de completitud de la madre (cierra un gap de Notion):** el promote (según Notion) solo chequea
  `is_ready`, pero `is_ready=true` no implica madre completa — un acknowledge sobre un finding deja
  `is_ready=true` aunque falten campos (p.ej. `closing_date`), y derivar el período de un `closing_date` NULL
  rompería. Se re-chequean los 10 obligatorios y, si falta alguno, se trata como `statement_not_ready` (no está
  listo para promover). Una madre completada por PUT pasa sin problema.
- **Resolver vigente antes que soft-deleted (§5.1):** evita reactivar una soft-deleted cuando hay vigente
  (rompería el índice parcial).
- **Motor tras el reviewer:** el motor lee `is_ready`; correrlo después garantiza que respete el resultado del
  reviewer (no materializa una tarjeta nueva ni una con `closing_day_changed`).
- **`user_id` del token; staging por pertenencia.**

---

## 7. Response

Notion no especifica el body de éxito. Devolvemos **200** con un resultado mínimo para que el front sepa el
estado de la tarjeta resultante (si quedó con findings, mostrar "Reconocer"):

```python
class PromoteResult(BaseModel):
    credit_card_id: uuid.UUID
    is_ready: bool
    review_findings: list[str]
```

El servicio devuelve la `CreditCard` (tras `review` + `motor` + `refresh`); el router arma `PromoteResult`
(`review_findings = json.loads(card.review_findings)`).

---

## 8. Tests (`tests/test_promote_credit_card_statements.py`)

Reusar `cc_catalog`, `_auth`, `_payload`, helpers del staging. Para promover hay que dejar la madre lista y los
ítems completos: cargar (POST), completar madre (PUT) e ítems (PUT items), o sembrar directo el staging listo
vía `db_session`. `today` real no afecta (el promote no usa fechas-vs-hoy salvo lo que herede el motor).

- **Tarjeta nueva (happy path):** staging listo, ítems completos, tasas presentes → 200; existe
  `credit_cards` nueva con `closing_day` = día del `closing_date`, `review_findings == ["closing_day_inferred"]`,
  `is_ready false`; existe `credit_card_statements` del período con sus items; el staging fue borrado; el motor
  **no** materializó (is_ready false → sin `cash_flow_entries`). `PromoteResult` refleja
  `closing_day_inferred`.
- **404:** sin staging.
- **409 `statement_not_ready`:** madre `is_ready=false`; y caso guarda: `is_ready=true` con un obligatorio NULL.
- **409 `items_incomplete`:** un ítem sin `item_type_id` (o cuotas inconsistentes).
- **409 `rates_required_new_card`:** tarjeta nueva y una tasa (o `rates_add_vat`) NULL.
- **409 `statement_period_exists`:** ya hay un statement del mismo período para la tarjeta existente.
- **409 `statement_period_not_after_last`:** período anterior/igual-en-mes al último (p.ej. último jun-2026,
  staging may-2026).
- **Tarjeta existente lista (sin closing_day_changed):** segundo período consecutivo, `closing_date.day` cercano
  (≤4) al `closing_day` → `is_ready true`, el motor materializa el resumen + proyecciones (hay
  `cash_flow_entries` del período).
- **`closing_day_changed`:** segundo período con `closing_date.day` lejos (>4) del `closing_day` →
  `review_findings == ["closing_day_changed"]`, `is_ready false`, motor no-op.
- **Reactivación de soft-deleted:** una `credit_cards` soft-deleted del mismo emisor+red → el promote la
  reactiva (`deleted_at NULL`) en vez de crear otra; no viola el índice.
- **Tasas no pisan en update:** tarjeta existente, staging con una tasa NULL → conserva la vigente.
- **Purchases:** ítem en cuotas → fila en `credit_card_purchases` (y al re-promover el período siguiente,
  actualiza `last_statement_closing_date`); ítem suscripción → fila nueva cada período; ítem de un pago no
  suscripción → no genera purchase.
- **401:** sin token.

> Helper sugerido: una función que deje el staging "listo" (madre completa + `is_ready=true` + ítems completos)
> sembrando por `db_session`, para no depender de toda la cadena POST→PUT en cada test.

---

## 9. Plan de implementación (orientativo)

Un slice (`feat/promote-credit-card-statements`), TDD:
1. 5 codes en `errors.py`; schema `PromoteResult`.
2. Tests (rojo) → servicio `promote_staging_statement` (validaciones + 5 pasos + reviewer + motor + borrado) +
   endpoint en el router (verde) → commit.
3. Suite completa verde → cierre.
