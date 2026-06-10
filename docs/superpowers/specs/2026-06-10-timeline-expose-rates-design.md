# timeline — exponer financing_rate / overdue_rate / minimum_payment — Diseño

> El `GET /cash-flow-entries` (timeline) expone por row tres datos que ya existen en `cash_flow_entries` pero
> hoy no salen: `financing_rate`, `overdue_rate` y `minimum_payment`. Sirven para que la web/app (y a futuro el
> PlanEngine) puedan razonar el costo de diferir un pago. Es un slice de **lectura**: no cambia montos ni la
> lógica de totales del timeline.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice. Toca `_TIMELINE_SQL` + `_entry_fields` + el schema
  `TimelineEntryOut` (`app/services/cash_flow_entry_service.py`, `app/schemas/cash_flow_entry.py`). Sin tabla
  nueva, sin migración (las columnas ya existen y están pobladas por el motor).
- **Cierre:** rama `feat/timeline-expose-rates`, **squash-merge** a `main`.
- **Fuera de alcance:** poblar `minimum_payment` en los meses proyectados de tarjeta (hoy null fuera del
  resumen) — eso va en otro slice tocando `CashFlowEngine.credit_cards`. Cualquier uso de estos campos (web,
  PlanEngine).

---

## 1. Punto de partida

Las columnas `financing_rate`, `overdue_rate` (numeric(5,2), nullable) y `minimum_payment` (numeric(12,2),
nullable) ya están en `cash_flow_entries` y el motor las llena (verificado en dev: la tarjeta `9e5f…` trae
84.18 / 97.60 por row, y `minimum_payment` solo en los resúmenes). Pero el `_TIMELINE_SQL` ni las selecciona,
y los schemas no las devuelven. Este slice las **expone**.

---

## 2. Cambio en `_TIMELINE_SQL`

Agregar las 3 columnas en cada CTE, propagándolas hasta el SELECT final. Origen por tipo de fuente:

| Rama (source_type) | financing_rate | overdue_rate | minimum_payment |
|---|---|---|---|
| `gasto` / `deuda` / `deuda_abierta` (obligations) | `COALESCE(cfe.financing_rate, 0)` | `COALESCE(cfe.overdue_rate, 0)` | `cfe.amount` |
| `ingreso` (incomes) | `0` | `0` | `0` |
| `plan_movimiento` / `plan_movimiento_entrada` | `COALESCE(cfe.financing_rate, 0)` | `COALESCE(cfe.overdue_rate, 0)` | `cfe.amount` |
| `tarjeta_credito` (credit_cards) | `COALESCE(cfe.financing_rate, 0)` | `COALESCE(cfe.overdue_rate, 0)` | `cfe.minimum_payment` |

- `entries_with_payments`: propagar `e.financing_rate, e.overdue_rate, e.minimum_payment` y agregarlos al
  `GROUP BY`.
- `open_debt_monthly`: `0 AS financing_rate, 0 AS overdue_rate, 0 AS minimum_payment` ubicados **antes** de
  `paid_real`/`planned_amount`, en el **mismo orden** que `entries_with_payments` (el `UNION ALL` que arma
  `unified` es posicional; si difiere, las rows de `deuda_abierta` saldrían con `financing_rate = paid_real`).
- SELECT final: agregar `u.financing_rate, u.overdue_rate, u.minimum_payment`.

`:user_id` / `:plan_id` siguen como bind params (sin hardcodear). El resto del SQL (montos, conversión,
`ORDER BY`) no cambia.

---

## 3. `_entry_fields`

Sumar las 3 lecturas del row: `financing_rate=r["financing_rate"]`, `overdue_rate=r["overdue_rate"]`,
`minimum_payment=r["minimum_payment"]`. Aplica igual a rows de mes y a `open_debts` (ambas pasan por
`_entry_fields`).

---

## 4. Schema (`app/schemas/cash_flow_entry.py`)

`TimelineEntryOut` (lo hereda `MonthEntryOut`) suma:

```python
    financing_rate: Decimal
    overdue_rate: Decimal
    minimum_payment: Decimal | None
```

`financing_rate` y `overdue_rate` van **no-null** (el SQL hace `COALESCE(...,0)`). `minimum_payment` es
**`Decimal | None`**: en las cuotas proyectadas de tarjeta hoy viene null (solo el resumen lo trae). `MonthOut`
no cambia (los campos son por-row, no agregados de mes).

---

## 5. Cambios de contrato

Las rows del timeline (meses y `open_debts`) suman 3 campos: `financing_rate`, `overdue_rate`,
`minimum_payment`. Aditivo: nada existente cambia de nombre, forma ni valor. Los totales por mes
(`available`/`pending_*`/`remaining_spending`/`balance`) no se tocan.

---

## 6. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow_entry_service.py` | `_TIMELINE_SQL` (3 campos en las 4 ramas + propagación + fix de orden en open_debt) y `_entry_fields` |
| `app/schemas/cash_flow_entry.py` | `TimelineEntryOut`: + `financing_rate`, `overdue_rate`, `minimum_payment` |
| `tests/test_get_cash_flow_entries.py` | tests de los 3 campos + 2 asserts en `test_open_debt_projected_into_month` (guarda del orden) |

---

## 7. Tests

- **Tarjeta:** una row de `tarjeta_credito` con `financing_rate`/`overdue_rate`/`minimum_payment` sembrados →
  la respuesta los trae; una cuota sin `minimum_payment` → `minimum_payment` null.
- **Ingreso:** una row de `ingreso` → `financing_rate == 0`, `overdue_rate == 0`, `minimum_payment == 0`.
- **`deuda_abierta` (guarda del Bug 2):** **plegado en el test existente** `test_open_debt_projected_into_month`
  (no un test nuevo). Ese test ya arma una `deuda_abierta` con un pago planificado; se le agrega un pago real y
  dos asserts sobre la proyección mensual: `financing_rate == 0` **y** `paid_real` correcto (no intercambiados
  por el orden del `UNION ALL`).
- Los tests existentes del timeline siguen verdes (cambio aditivo). `today` inyectado donde haga falta.

---

## 8. Plan de implementación (orientativo)

Un slice (`feat/timeline-expose-rates`), TDD: test de los 3 campos (rojo) → `_TIMELINE_SQL` + `_entry_fields` +
schema → sumar la guarda del Bug 2 al test `test_open_debt_projected_into_month` → suite verde → cierre
(squash-merge). Sin tocar Notion.
