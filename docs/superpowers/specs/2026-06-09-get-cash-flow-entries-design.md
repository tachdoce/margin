# GET /cash-flow-entries — la línea de tiempo — Diseño

> Segundo sub-proyecto del grupo **cash-flow-entries**: el endpoint de lectura del flujo de caja. Devuelve el
> `cash_flow_timeline` (entries reales + simuladas del plan, agrupadas por mes y flujo, con conversión a moneda
> legal y la proyección de `deuda_abierta`). En este slice va **solo `GET /cash-flow-entries`**; `by-source`
> y `PATCH /cash-flow-entries/{id}` quedan para un slice posterior.

- **Fecha:** 2026-06-09
- **Estado:** aprobado para implementar
- **Alcance:** **backend only** (la web del flujo va después).
- **Cierre:** rama `feat/get-cash-flow-entries`, **squash-merge** a `main`.
- **Fuente de verdad (Notion):** `Endpoints → Flujo de dinero → GET cash-flow-entries` y
  `BD → Flujo de dinero → cash_flow_entries` / `cash_flow_payments`.
- **Depende de:** los motores ya materializan `cash_flow_entries`; `cash_flow_payments` (slice anterior);
  tablas `currency_rates`, `obligations`, `incomes`, `plan_movements`, `credit_cards`, `institutions`,
  `credit_card_networks`.

---

## 1. Contrato

`GET /cash-flow-entries?plan_id={plan_id}` → 200 `cash_flow_timeline`. Solo lectura.

- `plan_id` **obligatorio** (define la capa de simulación). Si falta → 422 `plan_id_required`.
- El plan debe existir y ser del usuario autenticado. Si no → 404 `not_found`.
- 401 `unauthenticated` si no hay sesión.

**Response** `{ months: [...], open_debts: [...] }`:
- `months`: array ordenado cronológicamente. Cada mes: `month` (`YYYY-MM`), `total_income`,
  `total_expenses`, `balance` (en moneda legal), `incomes` (array de entries), `expenses` (array de entries).
- `open_debts`: array de entries sin fecha (las `deuda_abierta` madre).

**Cada entry** (fila de `cash_flow_entries`, agrupada — no objeto nuevo): `id`, `event_date` (solo en las de
`months`; las de `open_debts` **no** lo traen), `amount`, `paid_real`, `planned_amount`, `currency_id`,
`source_type`, `source_id`, `description`, `amount_converted`, `paid_real_converted`,
`planned_amount_converted`. **No** trae `is_income` (el grupo lo comunica).

- `paid_real`: suma de pagos reales (`plan_id IS NULL`). `planned_amount`: suma de planificados del `plan_id`
  pedido. Ambos derivados al vuelo, no columnas.
- `*_converted`: el monto llevado a moneda legal (× `currency_rates.value` de la fecha, ×1 si no hay fila).
- Subtotales del mes calculados sobre `amount_converted`.

> Pydantic v2 serializa `Decimal` como string. Por eso el response usa schemas Pydantic (no dicts crudos, que
> FastAPI serializaría como float).

---

## 2. Query (SQL crudo vía `text()`)

Decisión: la query se escribe como **SQL crudo** con `text()` y binds `:user_id` / `:plan_id`, espejando la
documentada en Notion. Es la primera SQL cruda en servicios (el resto es ORM); se justifica por la complejidad
(UNION ALL polimórfico con joins distintos por rama + `SUM FILTER` + `date_trunc` + proyección + conversión),
porque es read-only y porque conviene cotejarla 1:1 con el contrato.

Estructura (idéntica a Notion):

1. **CTE `entries`** — `UNION ALL` de 4 ramas, cada una con su JOIN (INNER) según `source_type`:
   - **obligations**: `source_type IN ('gasto','deuda','deuda_abierta')`, `description` de `obligations`.
   - **incomes**: `source_type = 'ingreso'`, `description` de `incomes`.
   - **plan_movements**: `source_type IN ('plan_movimiento','plan_movimiento_entrada')`, **filtra
     `pm.plan_id = :plan_id`**, `description` de `plan_movements`.
   - **credit_cards**: `source_type = 'tarjeta_credito'`, JOIN a `credit_cards` + `institutions` +
     `credit_card_networks`, `description = inst.name || ' ' || ccn.name`. **No** filtra `cc.deleted_at`
     (las tarjetas soft-deleted con pagos reales se siguen mostrando — decisión documentada en Notion).
   - Todas seleccionan: `id, event_date, amount, currency_id, source_type, source_id, is_income, description`.
   - Todas filtran `cfe.user_id = :user_id`.
2. **CTE `entries_with_payments`** — `LEFT JOIN cash_flow_payments` sobre `entries`, con
   `COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id IS NULL), 0) AS paid_real` y
   `COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0) AS planned_amount`. `GROUP BY` los campos de
   la entry.
3. **CTE `open_debt_monthly`** — proyección de `deuda_abierta` por mes: parte de `cash_flow_payments` JOIN
   `cash_flow_entries` (`source_type = 'deuda_abierta'`, `user_id = :user_id`) JOIN `obligations`, con
   `p.plan_id IS NULL OR p.plan_id = :plan_id`. `event_date = MIN(COALESCE(p.planned_date, p.created_at::date))`,
   `amount = COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0)`, más `paid_real`/`planned_amount`
   igual que arriba. `GROUP BY` entry + `date_trunc('month', COALESCE(p.planned_date, p.created_at::date))`.
4. **CTE `unified`** = `entries_with_payments UNION ALL open_debt_monthly`.
5. **SELECT final** — agrega los convertidos con `LEFT JOIN currency_rates cr ON cr.currency_id = u.currency_id
   AND cr.rate_date = COALESCE(u.event_date, CURRENT_DATE)`:
   `u.amount * COALESCE(cr.value, 1) AS amount_converted` (ídem `paid_real_converted`,
   `planned_amount_converted`). `ORDER BY u.event_date ASC NULLS LAST`.

La SQL literal completa está en la página Notion `GET cash-flow-entries → Lógica de implementación`; se copia
de ahí (es la fuente de verdad del query).

> **Heurística madre vs proyección de `deuda_abierta`:** la fila madre sale por `entries_with_payments` con
> `event_date NULL` (→ `open_debts`); las proyecciones salen por `open_debt_monthly` con `event_date` (→ meses).
> Comparten `id`. No hace falta flag: el `event_date` las distingue.

---

## 3. Armado de la estructura (Python, sobre el resultado)

El service recibe filas planas (entry + `description` + sumas + convertidos) y arma el `TimelineOut`:

- Fila **sin `event_date`** → `open_debts` (incluye la madre de cada `deuda_abierta`).
- Fila **con `event_date`** → mes `YYYY-MM` de `event_date`; dentro, según `is_income`, a `incomes` (true) o
  `expenses` (false).
- Mientras distribuye, acumula por mes sobre `amount_converted`: `total_income` (suma de `incomes`),
  `total_expenses` (suma de `expenses`), `balance = total_income - total_expenses`.
- Un mes aparece **solo si tiene al menos una entry**.
- Orden: meses cronológico ascendente; dentro de cada mes, `incomes`/`expenses` por `event_date` asc y como
  desempate por `id` asc. (El `ORDER BY` de la query ya deja las sin-fecha al final; el orden fino dentro del
  mes se asegura al armar.)
- `is_income` se usa solo para clasificar; **no** se serializa.

---

## 4. Schemas (`app/schemas/cash_flow_entry.py`)

```text
TimelineEntryOut(BaseModel):
    id, amount, paid_real, planned_amount, currency_id (int), source_type (str),
    source_id (uuid), description (str), amount_converted, paid_real_converted, planned_amount_converted
    # montos: Decimal

MonthEntryOut(TimelineEntryOut):
    event_date: date

MonthOut(BaseModel):
    month: str            # "YYYY-MM"
    total_income, total_expenses, balance: Decimal
    incomes: list[MonthEntryOut]
    expenses: list[MonthEntryOut]

TimelineOut(BaseModel):
    months: list[MonthOut]
    open_debts: list[TimelineEntryOut]
```

`open_debts` usa `TimelineEntryOut` (sin `event_date`); las de los meses usan `MonthEntryOut` (con
`event_date`). El service construye las instancias desde las filas.

---

## 5. Archivos

| Archivo | Responsabilidad |
|---|---|
| `app/routers/cash_flow_entries.py` | Router thin, `GET /cash-flow-entries`, `Depends(get_current_user)`. Registrar en `main.py`. |
| `app/services/cash_flow_entry_service.py` | `get_timeline(db, user, plan_id)`: valida, corre el `text()`, arma el `TimelineOut`. |
| `app/schemas/cash_flow_entry.py` | Los 4 schemas de §4. |

Códigos de error: **reusa** `plan_id_required` y `not_found` (ya existen). No hay códigos nuevos.

`plan_id` se recibe como `Query(default=None)` y, si es `None`, el service levanta `plan_id_required` (no se
deja a la validación de FastAPI, para devolver el code propio).

---

## 6. Tests (`tests/test_get_cash_flow_entries.py`)

Postgres `margin_test` (`create_all` + savepoint). Setup: crear las filas **fuente reales**
(obligation/income/plan_movement/credit_card) + insertar `CashFlowEntry` apuntándolas (`source_id`) + pagos.
(Helpers de inserción de entries/plans/pagos se pueden tomar del slice de pagos.)

- **422** `plan_id_required` (sin query param).
- **404** plan inexistente / de otro usuario.
- **Agrupación**: entries de varios tipos en meses distintos → estructura `months` correcta, cada una en su
  flujo (`incomes`/`expenses`), `is_income` ausente del JSON.
- **Subtotales**: `total_income`, `total_expenses`, `balance` por mes (sobre los convertidos).
- **Pagos derivados**: `paid_real` (suma reales), `planned_amount` (del plan pedido); un planificado de **otro**
  plan **no** suma; las entries reales son iguales cambiando de plan.
- **deuda_abierta**: la madre aparece en `open_debts` (sin `event_date`); con un pago planificado del plan,
  además proyectada en el mes del `planned_date` (en `expenses`, `amount = planned` del mes, mismo `id`).
- **description por fuente**: una entry de cada rama trae la `description` correcta; la de tarjeta como
  `"<emisor> <red>"`; una entry de tarjeta **soft-deleted** (su `credit_cards.deleted_at` con valor) **sí**
  aparece.
- **plan entries**: una entry `plan_movimiento` del plan pedido aparece; la de **otro** plan no.
- **conversión**: sin fila en `currency_rates` → `*_converted == *` (×1); con una fila `value` ≠ 1 para la
  fecha de la entry → `amount_converted = amount × value`.
- **orden**: meses ascendentes; dentro del mes por `event_date` y luego `id`.
- **vacío**: usuario sin entries → `{ "months": [], "open_debts": [] }`.

---

## 7. Plan de implementación (orientativo)

Un slice (`feat/get-cash-flow-entries`), TDD: schemas → service (query `text()` + armador) → router + registro
→ tests (de los simples a los compuestos) → suite verde → cierre. La conversión se implementa como documentado
(×1 hoy); el servicio que llena `currency_rates` queda fuera de alcance.
