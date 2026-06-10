# CashFlowEngine.credit_cards — relleno mensual con amount 0 hasta el horizonte — Diseño

> El motor de tarjetas (Responsabilidad 2 — proyección) hoy crea entries solo en los meses con cuota/suscripción
> pendiente. Pasamos a **densificar**: cada mes desde M+1 (M = mes del cierre) hasta el `HORIZON`, en **ambas
> monedas** (local y USD), tiene una entry; donde no hay actividad, `amount = 0`. El objetivo es tener una
> **base mensual por moneda** sobre la que más adelante se devengue financiación / mínimo sobre el saldo, aunque
> ese mes no caiga una cuota nueva.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice: densificar R2 en `CashFlowEngine.credit_cards` + actualizar los tests
  de tarjetas afectados.
- **Cierre:** rama `feat/credit-card-monthly-zero-fill`, **squash-merge** a `main`.
- **Fuera de alcance:** el cálculo de interés/mínimo sobre saldo en sí (otro slice); **filtrar/ocultar** las
  filas 0 en el GET o la web (otro slice); R1 (último resumen) no cambia.

---

## 1. Densificar la proyección (R2)

En [credit_cards.py](../../../backend/app/services/cash_flow/credit_cards.py) `materialize_credit_card`, R2 hoy
hace:

```python
for (y, m, cid), amount in _projection_sums(db, statement, horizon).items():
    ...
```

`_projection_sums` devuelve solo las claves `(año, mes, moneda)` con monto > 0. El cambio: tras obtener ese
dict, **rellenar** las claves faltantes con `Decimal("0")` para **cada mes M+1 → horizonte** y **cada moneda**
`(local_id, usd_id)`. El loop de R2 que arma los `targets` queda igual: ahora recorre un dict denso.

- Mes base = `statement.closing_date` (año/mes). Rango: `k = 1` hasta que `_add_months(base, k) > (horizon.year,
  horizon.month)` (misma cota que `_projection_sums`).
- Monedas: siempre las dos (`local_id`, `usd_id`), aunque la tarjeta nunca haya tenido movimiento en una.
- `setdefault`: si la clave ya existe (monto real proyectado), **no se pisa**; solo se agregan las que faltan.

---

## 2. Valores de las filas con amount 0

Salen del mismo loop de R2, así que heredan su lógica:

- `amount = 0`.
- `financing_rate` / `overdue_rate`: las tasas efectivas de la tarjeta por moneda (`rate_pair[cid]`) — las
  mismas que las filas proyectadas. Son la base para devengar después.
- `minimum_payment`: `0` (`0 * PROJECTED_MINIMUM_RATE`, cuantizado).
- `event_date`: misma lógica de vencimiento (`due_day` vs `closing_day`).
- `issue_year` / `issue_month`: el mes proyectado.

**R1 (mes del cierre, último resumen): sin cambios.** El relleno arranca en M+1.

---

## 3. Implementación

Helper nuevo en el mismo módulo, p. ej.:

```python
def _densify_projection(sums, statement, horizon, currency_ids):
    """Rellena con 0 cada (mes, moneda) faltante desde M+1 hasta el horizonte (in place)."""
    base_y, base_m = statement.closing_date.year, statement.closing_date.month
    horizon_key = (horizon.year, horizon.month)
    k = 1
    while True:
        y, m = _add_months(base_y, base_m, k)
        if (y, m) > horizon_key:
            break
        for cid in currency_ids:
            sums.setdefault((y, m, cid), Decimal("0"))
        k += 1
    return sums
```

En `materialize_credit_card`, R2:

```python
    sums = _projection_sums(db, statement, horizon)
    _densify_projection(sums, statement, horizon, (local_id, usd_id))
    for (y, m, cid), amount in sums.items():
        ...  # igual que hoy
```

No se toca `_reconcile`: ahora los `targets` son densos, así que casi no hay borrados de stale (las futuras
quedan todas en el target set) y el UPSERT crea/actualiza las filas 0.

---

## 4. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow/credit_cards.py` | helper `_densify_projection` + usarlo en R2 |
| `tests/test_cashflow_credit_cards.py` | tests del relleno + actualizar los que asertan claves/conteos exactos |

---

## 5. Tests

- **Relleno:** una tarjeta con una sola cuota (ej. junio) → existen entries `amount = 0` en local **y** USD para
  los meses sin cuota desde M+1 hasta el horizonte; el mes con cuota mantiene su monto real.
- **Ambas monedas:** un resumen solo-local igual genera filas USD con `amount = 0` cada mes.
- **Tasas/mínimo en las filas 0:** `financing_rate`/`overdue_rate` = las de la tarjeta; `minimum_payment = 0`.
- **R1 intacto:** la fila del último resumen mantiene su monto y `minimum_payment` real.
- **Actualizar los tests existentes** que asumen ausencia de meses (`assert (a,b,c) not in keys`) o cuentan
  entries: con el relleno, cada mes M+1→horizonte existe en las dos monedas. Es el grueso del trabajo del slice.

---

## 6. Consecuencias asumidas

- **El GET del timeline devolverá muchas filas con `amount = 0`** (la tarjeta en cada mes hasta el horizonte, en
  ambas monedas). Los **totales del mes no cambian** (amount 0 → no suma a `pending_*`), pero las filas aparecen
  en la respuesta y en la web Flujo. Ocultarlas/filtrarlas es otro slice.
- **Volumen:** ~(meses hasta 2027-12) × 2 monedas por tarjeta. Aceptado.

---

## 7. Plan de implementación (orientativo)

Un slice (`feat/credit-card-monthly-zero-fill`), TDD: test del relleno (rojo) → `_densify_projection` + uso en
R2 → actualizar los tests de claves/conteos → suite verde → cierre (squash-merge). Sin tocar Notion.
