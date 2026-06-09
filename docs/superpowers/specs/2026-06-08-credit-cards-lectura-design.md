# Credit-cards — Lectura (GET ×3) — Diseño

> Sub-proyecto #1 de los endpoints de **credit-cards** (la tarjeta ya promovida). Los tres GET de solo
> lectura: lista de tarjetas, historial de resúmenes de una tarjeta, y cargos de un resumen. Fundan los
> schemas de salida (`CreditCardOut`, `StatementOut`, `StatementItemOut`) que reusan los sub-proyectos
> #2–#4. El *qué* está en Notion → Endpoints → Tarjetas de crédito → `GET credit-cards`,
> `GET credit-cards-statements`, `GET credit-cards-statements-items`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tablas `credit_cards`, `credit_card_statements`, `credit_card_statement_items` (ya en el
  repo).
- **Cierre:** rama `feat/credit-cards-lectura`, **squash-merge** a `main`. Al terminar, **actualizar las 3
  páginas de Notion** para reflejar el envoltorio (ver §6).

---

## 1. Alcance

Tres endpoints solo-lectura (sin transacción de escritura, sin reviewer):
- `GET /credit-cards` — todas las tarjetas del usuario (vigentes + soft-deleted), con `is_deleted`.
- `GET /credit-cards/{id}/statements` — historial de resúmenes de una tarjeta.
- `GET /credit-cards/{id}/statements/{statement_id}/items` — cargos de un resumen.

**Fuera de alcance:** PATCH/acknowledge/DELETE de `credit-cards` (#2, #3) y DELETE de statements (#4).

---

## 2. Capa y archivos

- Router `app/routers/credit_cards.py` (tag `credit-cards`), registrado en `main.py`. Pensado para crecer con
  #2–#4.
- Servicio `app/services/credit_card_service.py`: `list_credit_cards`, `list_statements`,
  `list_statement_items`. Solo lectura; lanza `AppError(not_found)` donde corresponde.
- Schemas `app/schemas/credit_card.py`: `CreditCardOut`, `StatementOut`, `StatementItemOut`.

**Respuestas envueltas** (decisión del usuario, consistente con el resto del backend): `{"credit_cards": [...]}`,
`{"statements": [...]}`, `{"items": [...]}`.

---

## 3. GET /credit-cards

Solo lectura.
1. Leer todas las `credit_cards` con `user_id` = usuario (vigentes **y** soft-deleted), orden estable por
   `created_at`.
2. Por cada una, `CreditCardOut`: datos de negocio (`institution_id`, `card_network_id`, `current_limit`,
   `closing_day`, las 4 tasas **crudas**, `rates_add_vat`) + `review_findings` (lista, `json.loads`) +
   `is_ready` + `is_deleted` (`deleted_at is not None`). **No** expone `reviewed_at`/`user_acknowledged_at`/
   `deleted_at` (solo el booleano).
3. `{"credit_cards": [...]}` (`[]` si no tiene). Nunca 404.

```python
class CreditCardOut(BaseModel):
    id: uuid.UUID
    institution_id: int
    card_network_id: int
    current_limit: Decimal
    closing_day: int
    financing_rate_local: Decimal
    overdue_rate_local: Decimal
    financing_rate_usd: Decimal
    overdue_rate_usd: Decimal
    rates_add_vat: bool
    review_findings: list[str]
    is_ready: bool
    is_deleted: bool

    @classmethod
    def from_model(cls, c: CreditCard) -> "CreditCardOut":
        return cls(
            id=c.id, institution_id=c.institution_id, card_network_id=c.card_network_id,
            current_limit=c.current_limit, closing_day=c.closing_day,
            financing_rate_local=c.financing_rate_local, overdue_rate_local=c.overdue_rate_local,
            financing_rate_usd=c.financing_rate_usd, overdue_rate_usd=c.overdue_rate_usd,
            rates_add_vat=c.rates_add_vat,
            review_findings=json.loads(c.review_findings), is_ready=c.is_ready,
            is_deleted=c.deleted_at is not None,
        )
```

---

## 4. GET /credit-cards/{id}/statements

Solo lectura.
1. La tarjeta `{id}` existe y es del usuario (**sin** filtrar `deleted_at`: el historial se ve aunque esté
   soft-deleted). Si no → 404 `not_found`.
2. Leer `credit_card_statements` con `credit_card_id = {id}`, orden `issue_year` DESC, `issue_month` DESC.
3. `{"statements": [...]}` (`[]` si no hay).

```python
class StatementOut(BaseModel):
    id: uuid.UUID
    issue_year: int
    issue_month: int
    closing_date: date
    due_date: date
    total_local: Decimal
    total_usd: Decimal
    minimum_payment_local: Decimal
    minimum_payment_usd: Decimal
    # from_model directo
```

---

## 5. GET /credit-cards/{id}/statements/{statement_id}/items

Solo lectura.
1. La tarjeta `{id}` existe y es del usuario (sin filtrar `deleted_at`), **y** el `credit_card_statements`
   `{statement_id}` existe y su `credit_card_id` es esa tarjeta. Si algo falla → 404 `not_found`.
2. Leer `credit_card_statement_items` con `credit_card_statement_id = {statement_id}`, orden `charge_date`.
3. `{"items": [...]}` (`[]` si no hay).

```python
class StatementItemOut(BaseModel):
    id: uuid.UUID
    charge_date: date
    description: str
    amount: Decimal
    currency_id: int
    current_installment: int | None
    total_installments: int | None
    item_type_id: int
    # from_model directo
```

---

## 6. Decisiones, con su porqué

- **Respuestas envueltas (`{"credit_cards": [...]}`, etc.):** consistencia con los GET existentes del backend
  (`debts`/`incomes`/`plans` envuelven). Notion dibuja array crudo; al cerrar este sub-proyecto se actualizan
  las 3 páginas de Notion al envoltorio.
- **`GET /credit-cards` lista vigentes + soft-deleted con `is_deleted`:** el front ubica las borradas; un solo
  endpoint para todas.
- **Historial e ítems visibles con tarjeta soft-deleted:** el historial es lo que sobrevive a un soft-delete;
  por eso las queries de #4/#5 no filtran `deleted_at` de la tarjeta.
- **Tasas crudas (no efectivas):** el IVA se resuelve recién al materializar; el GET muestra lo guardado.
- **Solo lectura:** ningún GET dispara el reviewer ni recalcula `is_ready`.
- **`user_id` del token; tarjeta/resumen por pertenencia.** No se expone metadata de ciclo ni `deleted_at`
  como timestamp.

---

## 7. Tests (`tests/test_credit_cards_read.py`)

Reusar `seed_cc_refs`/`_card_kwargs` y el patrón de auth (`/auth/register` → token). Sembrar tarjetas y
statements/items vía `db_session` para el usuario registrado.

**GET /credit-cards:**
- **Vacío:** sin tarjetas → `{"credit_cards": []}`.
- **Lista con vigente + soft-deleted:** dos tarjetas (una `deleted_at` con valor) → ambas aparecen;
  `is_deleted` correcto; `review_findings` como lista; no aparecen `reviewed_at`/`deleted_at`.
- **Solo del usuario:** una tarjeta de otro usuario no aparece.
- **401** sin token.

**GET /credit-cards/{id}/statements:**
- **Orden desc:** dos statements (2026/04 y 2026/05) → 05 primero.
- **404:** tarjeta inexistente / de otro usuario.
- **Soft-deleted:** tarjeta soft-deleted con statements → 200 con el historial.
- **Vacío:** tarjeta sin statements → `{"statements": []}`.
- **401.**

**GET /credit-cards/{id}/statements/{statement_id}/items:**
- **200:** items del statement (cuotas + un pago) con sus campos.
- **404:** tarjeta de otro usuario; statement inexistente; statement de **otra** tarjeta del mismo usuario.
- **401.**

---

## 8. Plan de implementación (orientativo)

Un slice (`feat/credit-cards-lectura`), TDD:
1. Schemas + servicio + router + registro en `main.py`; tests (rojo → verde) → commit.
2. Suite completa verde → cierre.
3. Post-cierre: actualizar las 3 páginas de Notion al envoltorio.
