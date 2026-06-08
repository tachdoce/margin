# PUT /credit-card-statements (madre + ítem) — Diseño

> Sub-proyecto del subdominio **Tarjetas de crédito** (capa de endpoints). Los dos PUT que permiten al usuario
> **completar y corregir** el staging antes de promover: la fila madre (`staging_credit_cards`) y un ítem
> (`staging_credit_card_items`). Reemplazo total; sólo persisten si quedan **completos**. El *qué* está en
> Notion → Endpoints → Tarjetas de crédito → `PUT staging-credit-card-statements` y
> `PUT staging-credit-card-statements item`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tablas de staging, catálogos (`institutions`, `credit_card_networks`, `currencies`,
  `credit_card_item_types`, `credit_card_purchases`), el reviewer
  `review_staging_credit_card`, y el sub-proyecto `POST /credit-card-statements` (schemas/servicio/router ya
  creados). Reusa `scoping.require_user_currency`.
- **Cierre:** rama `feat/put-credit-card-statements`, **squash-merge** a `main`.

---

## 1. Alcance

Agregar al recurso ya existente:
- `PUT /credit-card-statements` — reemplaza los datos generales de la madre del usuario (sin id en ruta).
- `PUT /credit-card-statements/items/{item_id}` — reemplaza un ítem del usuario.

Ambos en una transacción; reemplazo total; persisten sólo si quedan completos (si no, 422 con code
específico). El PUT madre vuelve a correr el reviewer y puede heredar tipos; el PUT ítem no corre reviewer.

**Fuera de alcance:** `GET`, `DELETE`, `promote`, `acknowledge`, endpoints de `credit-cards`.

---

## 2. Error codes nuevos (`app/core/errors.py`)

| code | status | mensaje |
|---|---|---|
| `card_network_invalid` | 422 | `Red de tarjeta no válida.` |
| `statement_incomplete` | 422 | `El resumen quedaría incompleto.` |
| `item_type_invalid` | 422 | `Tipo de ítem no válido.` |
| `item_incomplete` | 422 | `El ítem quedaría incompleto.` |

Ya existen y se reusan: `not_found` (404), `institution_invalid`, `amount_invalid`, `currency_not_available`,
`installments_invalid`. (`institution_invalid` conserva su mensaje actual "Institución no válida.")

---

## 3. PUT /credit-card-statements (madre)

**Request `StagingMadreUpdate`** — todos los campos editables; en el schema **opcionales** (la completitud la
valida el servicio, para emitir `statement_incomplete` en vez de un 422 genérico de Pydantic). Pydantic sólo
valida tipos.

```python
class StagingMadreUpdate(BaseModel):
    institution_id: int | None = None
    card_network_id: int | None = None
    closing_date: date | None = None
    due_date: date | None = None
    current_limit: Decimal | None = None
    total_local: Decimal | None = None
    total_usd: Decimal | None = None
    minimum_payment_local: Decimal | None = None
    minimum_payment_usd: Decimal | None = None
    financing_rate_local: Decimal | None = None
    overdue_rate_local: Decimal | None = None
    financing_rate_usd: Decimal | None = None
    overdue_rate_usd: Decimal | None = None
    rates_add_vat: bool | None = None
```

**Servicio `update_staging_madre(db, user, payload) -> StagingCreditCard`. Validaciones en orden:**
1. La madre del usuario existe (`staging_credit_cards` por `user_id`, `with_for_update`). Si no → 404
   `not_found`.
2. Los **10 obligatorios** no-NULL: `institution_id`, `card_network_id`, `closing_date`, `due_date`,
   `current_limit`, `total_local`, `total_usd`, `minimum_payment_local`, `minimum_payment_usd`,
   `rates_add_vat`. Falta alguno → 422 `statement_incomplete`. (Las 4 tasas pueden ser NULL.)
3. `institution_id` existe + país del usuario → si no, 422 `institution_invalid`.
4. `card_network_id` existe + país del usuario → si no, 422 `card_network_invalid`.
5. `current_limit > 0` y `total_local`/`total_usd`/`minimum_payment_local`/`minimum_payment_usd` `>= 0` → si
   no, 422 `amount_invalid`.

**Update + herencia.** Antes de escribir, leer `prev_institution_id` / `prev_card_network_id`. Reemplazar
todos los campos editables (tasas tal como vengan, con valor o NULL); `updated_at = now()`. **Herencia de tipo
solo si** `(prev_institution_id is None or prev_card_network_id is None)` **y** ambos quedaron no-NULL: traer
de `credit_card_purchases` el `item_type_id` más reciente por `description` (misma query que el POST —
`_inherited_types`) y asignarlo **solo a los ítems de la madre cuyo `item_type_id` es NULL** y `description`
matchea exacto (el tipo manual previo prevalece).

**Reviewer + commit.** Correr `review_staging_credit_card(db, madre.id)` en la misma transacción; rollback si
lanza. `commit`. Devolver la madre.

**Response 200 `StagingMadreOut`** (campos de la madre + `review_findings` lista + `is_ready`; **sin** ítems).

---

## 4. PUT /credit-card-statements/items/{item_id} (ítem)

**Request `StagingItemUpdate`** — opcionales en schema, completitud validada por el servicio.

```python
class StagingItemUpdate(BaseModel):
    charge_date: date | None = None
    description: str | None = None
    amount: Decimal | None = None
    currency_id: int | None = None
    item_type_id: int | None = None
    current_installment: int | None = None
    total_installments: int | None = None
```

**Servicio `update_staging_item(db, user, item_id, payload) -> StagingCreditCardItem`. Validaciones en orden:**
1. El ítem existe y su madre es del usuario (join `staging_credit_cards.user_id == user.id`). Si no → 404
   `not_found`.
2. Obligatorios presentes: `charge_date`, `description`, `amount`, `currency_id`, `item_type_id`; y
   `description.strip()` largo ≥ 1. Falta alguno / descripción vacía → 422 `item_incomplete`.
3. `currency_id` del país del usuario **y** `allowed_in_credit_card = true` → si no, 422
   `currency_not_available`. (Reusar `require_user_currency` para país/existencia; además chequear
   `allowed_in_credit_card`, mismo code.)
4. `amount > 0` → si no, 422 `amount_invalid`.
5. `item_type_id` existe en `credit_card_item_types` → si no, 422 `item_type_invalid`.
6. **Cuotas:** si `current_installment` y `total_installments` no son ambos NULL, deben ser ambos con valor y
   cumplir `current_installment >= 1`, `total_installments >= 1`, `current_installment <= total_installments`.
   Si falla → 422 `installments_invalid`.

**Update.** Reemplazar los campos editables (`updated_at = now()`); cuotas tal como vengan (ambas o ambas
NULL). **No** corre reviewer (los ítems no llevan ciclo). `commit`. Devolver el ítem.

**Response 200 `StagingStatementItemOut`** (ya existe; `missing_fields` recalculado, vacío porque la
completitud es condición para persistir).

---

## 5. Refactor de schemas (DRY)

Extraer `StagingMadreOut` (los campos de la madre + `review_findings` + `is_ready`, con
`from_model(madre)`), y dejar `StagingStatementOut(StagingMadreOut)` agregando `items` (su `from_model(madre,
items)` arma la base con `StagingMadreOut.from_model` + los ítems). El `POST` sigue devolviendo
`StagingStatementOut`; el `PUT` madre devuelve `StagingMadreOut`.

---

## 6. Decisiones, con su porqué

- **Campos opcionales en el schema + completitud en el servicio:** el contrato exige codes específicos
  (`statement_incomplete` / `item_incomplete`); si los campos fueran requeridos en Pydantic, un faltante daría
  un 422 genérico con otro formato. La validación de negocio vive en el servicio.
- **Herencia condicionada al cambio NULL→resuelto:** sólo cuando recién ahora se conoce la tarjeta tiene
  sentido heredar; si ya estaba resuelta, el usuario editó otra cosa y no se re-hereda. El tipo manual del
  usuario nunca se pisa (solo se completa lo que está en NULL).
- **PUT ítem no corre reviewer:** los ítems no tienen ciclo; el `is_ready` de la madre no depende de ellos (la
  completitud de ítems se chequea al promover).
- **`currency_not_available` también por `allowed_in_credit_card`:** en tarjetas sólo Peso/Dólar; una moneda
  del país pero no admitida en tarjeta se rechaza con el mismo code.
- **`StagingMadreOut` extraído:** evita duplicar el mapeo de la madre entre POST y PUT.
- **`user_id` del token, nunca del body; staging/ítem resueltos por pertenencia al usuario.**

---

## 7. Tests (extender `tests/test_credit_card_statements.py`)

Reusar `cc_catalog`, `_auth`, `_payload`. Para tener un staging, hacer primero `POST`. Helpers nuevos para el
body de PUT madre (completo, válido) y PUT ítem.

**PUT madre:**
- **200 completa:** POST → PUT con todos los obligatorios → 200; la madre queda con los valores; `is_ready`
  refleja el reviewer (p.ej. sin tarjeta y emisor+red puestos → `new_card`; con tasas y fechas sanas, sin
  card → `new_card`).
- **404 sin staging:** PUT sin haber cargado → 404 `not_found`.
- **422 `statement_incomplete`:** falta un obligatorio (p.ej. `total_local=None`).
- **422 `institution_invalid`:** `institution_id` de otro país / inexistente.
- **422 `card_network_invalid`:** `card_network_id` inexistente.
- **422 `amount_invalid`:** `current_limit=0`, o un total negativo.
- **Tasas NULL OK:** las 4 tasas en null → 200 (no son obligatorias).
- **Herencia al resolver:** cargar con emisor/red que **no** resuelven (quedan NULL) + existir una
  `credit_cards` + `credit_card_purchases` (GOOGLE, tipo X); el ítem GOOGLE queda con `item_type_id` NULL tras
  el POST; el PUT que setea `institution_id`/`card_network_id` correctos → el ítem GOOGLE hereda X; un ítem ya
  clasificado a mano no se pisa.
- **Sin re-herencia si ya estaba resuelta:** POST con tarjeta resuelta, luego PUT que cambia otra cosa → no
  re-asigna tipos (un ítem dejado en NULL sigue NULL).

**PUT ítem:**
- **200 completa:** completar el ítem incompleto → 200, `missing_fields == []`, valores persistidos.
- **404:** `item_id` inexistente; ítem de otro usuario (otro token) → 404.
- **422 `item_incomplete`:** falta `amount`, o `description` vacía/whitespace.
- **422 `currency_not_available`:** `currency_id` no admitido en tarjeta (p.ej. Unidad Indexada) o de otro
  país.
- **422 `amount_invalid`:** `amount <= 0`.
- **422 `item_type_invalid`:** `item_type_id` inexistente.
- **422 `installments_invalid`:** solo una cuota; `current_installment > total_installments`; valor < 1.
- **Pago único:** ambas cuotas NULL → 200.
- **401:** sin token, ambos endpoints.

> Tests vía `client` + token. Para el caso "ítem de otro usuario", registrar un segundo usuario y usar su
> token contra el `item_id` del primero.

---

## 8. Plan de implementación (orientativo)

Un slice (`feat/put-credit-card-statements`), TDD:
1. Codes nuevos en `errors.py`; schemas (refactor `StagingMadreOut` + `StagingMadreUpdate` + `StagingItemUpdate`).
2. Tests (rojo) → servicio (`update_staging_madre`, `update_staging_item`) + router (2 endpoints) (verde) →
   commit.
3. Suite completa verde → cierre.
