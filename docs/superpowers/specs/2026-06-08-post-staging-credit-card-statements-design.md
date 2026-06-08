# POST /credit-card-statements (carga a staging) — Diseño

> Sub-proyecto del subdominio **Tarjetas de crédito** (capa de endpoints). Carga un estado de cuenta (payload
> de IA o JSON pegado) a **staging** (`staging_credit_cards` + `staging_credit_card_items`), resolviendo
> catálogos sin cortar, heredando el tipo de compras previas, y corriendo el reviewer. **Solo el POST.** El
> *qué* está en Notion → Backend → Endpoints → Tarjetas de crédito → `POST staging-credit-card-statements`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tablas `staging_credit_cards`/`staging_credit_card_items`, catálogos `institutions`,
  `credit_card_networks`, `currencies`, `credit_card_purchases`; el reviewer
  `app/services/review/staging_credit_cards.py` (ya hecho). Patrón router→service de `debts`.
- **Cierre:** rama `feat/post-credit-card-statements`, **squash-merge** a `main`.

---

## 1. Alcance

Implementar `POST /credit-card-statements`: recibe el JSON del resumen, hace UPSERT de la fila madre del
staging por `user_id` + borra y recrea sus ítems, resuelve catálogos a id-o-NULL, hereda `item_type_id` de
compras previas, corre `review_staging_credit_card`, y responde 201 con la madre + ítems (cada ítem con
`missing_fields` al vuelo). Todo en **una transacción**.

**Fuera de alcance:** `PUT` (completar madre / ítem), `GET`, `DELETE`, `promote`, los endpoints de
`credit-cards`. Sub-proyectos posteriores. La IA que produce el payload (vive fuera del backend).

---

## 2. Capa y archivos

- Router `app/routers/credit_card_statements.py` (tag `credit-card-statements`), registrado en `main.py`.
  `POST /credit-card-statements`, `Depends(get_current_user)`, `status_code=201`. Pensado para crecer con los
  próximos endpoints del recurso.
- Servicio `app/services/credit_card_statement_service.py` con
  `create_staging_statement(db, user, payload) -> StagingCreditCard` (devuelve la madre; los ítems se leen por
  relación/consulta al serializar). El servicio controla la transacción (`commit`), lanza `AppError`, no
  conoce HTTP.
- Schemas `app/schemas/credit_card_statement.py`: `StagingStatementCreate` (+ sub-modelos anidados) y
  `StagingStatementOut` (+ `StagingStatementItemOut`).

---

## 3. Request — schema lenient

El body es el JSON del resumen. **Todo opcional**: el contrato repite "ningún caso corta la carga / no fallan
si vienen", así que el schema **no** rechaza por datos faltantes (sin 422 por ausencia). Pydantic sí valida
**tipos** (un `amount` no numérico o una fecha mal formada → 422); eso es estructural, no "dato faltante".

```python
class GeneralData(BaseModel):
    issuer: str | None = None
    card_network: str | None = None
    closing_date: date | None = None
    due_date: date | None = None
    current_limit: Decimal | None = None

class PaymentSummary(BaseModel):
    total_local: Decimal | None = None
    total_usd: Decimal | None = None
    minimum_payment_local: Decimal | None = None
    minimum_payment_usd: Decimal | None = None

class ChargeIn(BaseModel):
    date: date | None = None
    description: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    current_installment: int | None = None
    total_installments: int | None = None

class AnnualEffectiveRates(BaseModel):
    vat_excluded: bool | None = None
    financing_rate_local_this_month: Decimal | None = None
    overdue_rate_local_this_month: Decimal | None = None
    financing_rate_usd_this_month: Decimal | None = None
    overdue_rate_usd_this_month: Decimal | None = None
    financing_rate_local_next_month: Decimal | None = None
    overdue_rate_local_next_month: Decimal | None = None
    financing_rate_usd_next_month: Decimal | None = None
    overdue_rate_usd_next_month: Decimal | None = None

class StagingStatementCreate(BaseModel):
    general_data: GeneralData = GeneralData()
    payment_summary: PaymentSummary = PaymentSummary()
    charges: list[ChargeIn] = []
    annual_effective_rates: AnnualEffectiveRates = AnnualEffectiveRates()
    # payments / others: se aceptan y se ignoran (no declarados; Pydantic por defecto los descarta)
```

> `user_id` **nunca** viene en el body: sale del token (`Depends(get_current_user)`).

---

## 4. Lógica del servicio (una transacción)

**4.1 Resolver catálogos (no cortan; id o `None`).** Por `users.country_code` del usuario:
- `issuer` → `institutions` por `name` (igualdad exacta) + `country_code`. id o NULL.
- `card_network` → `credit_card_networks` por `name` + `country_code`. id o NULL.
- cada `charge.currency` → `currencies` por `name` + `country_code` + `allowed_in_credit_card = true`. id o NULL.

No se reusa `scoping.require_user_currency` (ese **lanza** ante no-match); acá el no-match es válido → NULL.
Queries propias que devuelven id o `None`.

**4.2 Tasas.** Para cada una de las 4: `COALESCE(*_next_month, *_this_month)` (prioriza mes próximo). Si ambos
NULL → NULL. `rates_add_vat = (not vat_excluded)` si `vat_excluded` no es None; si es None → `rates_add_vat`
NULL.

**4.3 UPSERT de la madre por `user_id`.** Buscar `staging_credit_cards` del usuario (UNIQUE user_id). Si
existe, actualizar todas las columnas de negocio (mismo `id`); si no, crear. En ambos casos **resetear el
ciclo**: `reviewed_at=None`, `review_findings='[]'`, `user_acknowledged_at=None`, `is_ready=False`. Columnas
desde el payload resuelto (institution_id, card_network_id, closing_date, due_date, current_limit, totales,
mínimos, las 4 tasas, rates_add_vat), NULL donde no vino/no resolvió.

**4.4 Ítems: borrar y recrear.** Borrar todos los `staging_credit_card_items` de la madre (si existía) e
insertar uno por `charge` tal como venga: `charge_date=date`, `description`, `amount`, `currency_id` (resuelto
4.1 o NULL), `current_installment`/`total_installments` tal cual (cada uno o NULL), `item_type_id=NULL` (se
puede setear por herencia, 4.5). No se valida el par de cuotas.

**4.5 Herencia de `item_type_id`.** Solo si `institution_id` **y** `card_network_id` resolvieron (ambos
no-NULL). Traer, de `credit_card_purchases` de la tarjeta del usuario (`credit_cards` con ese user+emisor+red),
el `item_type_id` más reciente por `description` (`last_statement_closing_date DESC`). A cada ítem recién
insertado cuyo `description` matchee (igualdad exacta) se le asigna ese `item_type_id`. (Equivale al CTE
`ROW_NUMBER() ... PARTITION BY description ORDER BY last_statement_closing_date DESC` del contrato; se puede
implementar con esa query o en Python tras traer las compras de la tarjeta.)

**4.6 Reviewer.** Tras escribir, en la misma transacción, `review_staging_credit_card(db, madre.id)` (puebla
`review_findings`/`is_ready`). Si lanza, rollback. `commit`. Devolver la madre.

---

## 5. Response 201 — `StagingStatementOut`

Madre + ítems. `review_findings` como `list[str]` (json.loads). Cada ítem con `missing_fields` calculado al
serializar.

```python
class StagingStatementItemOut(BaseModel):
    id: uuid.UUID
    charge_date: date | None
    description: str | None
    amount: Decimal | None
    currency_id: int | None
    current_installment: int | None
    total_installments: int | None
    item_type_id: int | None
    missing_fields: list[str]

class StagingStatementOut(BaseModel):
    id: uuid.UUID
    institution_id: int | None
    card_network_id: int | None
    closing_date: date | None
    due_date: date | None
    current_limit: Decimal | None
    total_local: Decimal | None
    total_usd: Decimal | None
    minimum_payment_local: Decimal | None
    minimum_payment_usd: Decimal | None
    financing_rate_local: Decimal | None
    overdue_rate_local: Decimal | None
    financing_rate_usd: Decimal | None
    overdue_rate_usd: Decimal | None
    rates_add_vat: bool | None
    review_findings: list[str]
    is_ready: bool
    items: list[StagingStatementItemOut]
```

**`missing_fields` (regla, ver `BD → staging_credit_card_items`):** lista, en orden de columna, de
`charge_date`, `description`, `amount`, `currency_id`, `item_type_id` cuando estén en NULL; y de las cuotas, el
que falte (`current_installment` o `total_installments`) cuando venga **solo uno** de los dos. Si ambos NULL o
ambos con valor, las cuotas no aportan a `missing_fields`. Vacío = ítem completo.

---

## 6. Decisiones, con su porqué

- **Schema lenient (todo opcional):** el contrato insiste en "sin cortar"; la completitud la corrige el
  usuario por PUT antes de promover. Sólo 422 por tipos mal formados (responsabilidad de Pydantic), nunca por
  ausencia de datos.
- **No reusar `require_user_currency`:** ese helper lanza ante no-match (es para campos que el usuario elige);
  acá el no-match es esperable y entra NULL. Resolución propia id-o-None.
- **UPSERT por `user_id` + reset del ciclo:** un solo staging por usuario (UNIQUE); recargar pisa el anterior y
  lo manda de nuevo a la cola del reviewer (`reviewed_at=None`).
- **Herencia sólo con tarjeta resuelta:** sin emisor+red no se sabe contra qué tarjeta comparar; los ítems
  quedan en NULL y el usuario asigna el tipo.
- **`missing_fields` derivado, no persistido:** regla del proyecto (no se persiste lo derivable); se calcula al
  serializar.
- **`user_id` del token, nunca del body:** invariante de seguridad del proyecto.
- **Reviewer en la misma transacción:** el endpoint corre el `ReviewEngine` como paso siguiente a la escritura;
  rollback total si falla.

---

## 7. Tests (`tests/test_credit_card_statements.py`, vía `client`)

Sembrar (extender fixtures): país UY + Peso(1) + USD/Dólar(3, allowed_in_credit_card) + institución(1,
"Scotiabank") + red(1, "Amex") + tipos de ítem (compra/…); registrar y autenticar un usuario (token) — reusar
el patrón de `tests/test_debts.py`.

- **201 carga completa:** el request del ejemplo → 201; madre con institution/network resueltos, totales,
  tasas = `COALESCE(next, this)`, `rates_add_vat = not vat_excluded`; 2 ítems con su `currency_id` resuelto
  (Peso/Dólar) y `missing_fields == ["item_type_id"]`.
- **Resolución a NULL:** `issuer`/`card_network`/`currency` que no matchean (o no vienen) → ids NULL; `currency`
  de un cargo no listado (ej. "Euro") → `currency_id` NULL.
- **Tasas fallback:** `*_next_month` null → toma `*_this_month`; ambos null → NULL.
- **`rates_add_vat`:** `vat_excluded=false` → true; `true` → false; ausente → NULL.
- **UPSERT pisa:** dos POST seguidos del mismo usuario → un solo `staging_credit_cards` (mismo id), ítems del
  segundo (los del primero borrados).
- **Ítem incompleto:** cargo sin `date`/`amount`/`currency` y con solo `current_installment` →
  `missing_fields` incluye `charge_date`, `amount`, `currency_id`, `total_installments`, `item_type_id`.
- **Herencia de tipo:** con una `credit_cards` del usuario (emisor+red) y un `credit_card_purchases`
  `description="GOOGLE *COM PULSO PULS"` con `item_type_id` X → al cargar, el ítem GOOGLE hereda X
  (`missing_fields` sin `item_type_id`); sin tarjeta resuelta, no hereda.
- **Reviewer corrió:** la respuesta trae `review_findings`/`is_ready` poblados (p.ej. `new_card` si no hay
  tarjeta y emisor+red resolvieron; `rates_not_updated` si falta una tasa).
- **401:** sin token → 401 `unauthenticated`.

> Tests de endpoint usan el `client` (TestClient) + token, no llaman al servicio directo. Decimales viajan como
> string en el JSON (Pydantic v2).

---

## 8. Plan de implementación (orientativo)

Un slice (`feat/post-credit-card-statements`), TDD:
1. Tests de endpoint (rojo) → schemas + servicio + router + registro en `main.py` (verde) → commit.
2. Suite completa verde → cierre.
