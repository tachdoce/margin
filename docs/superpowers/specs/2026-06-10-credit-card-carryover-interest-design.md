# timeline — arrastre del saldo impago de tarjeta + interés — Diseño

> En el `GET /cash-flow-entries`, el **saldo impago del mes anterior** de una tarjeta (lo que no se pagó del
> resumen/cuota) se arrastra al **mes actual**, en la **misma moneda**, **con interés**. El interés lo calcula
> una función encapsulada (placeholder que evolucionará). Es lógica de **lectura**: no persiste nada.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice: función de interés + segunda pasada en `get_timeline`.
- **Cierre:** rama `feat/credit-card-carryover-interest`, **squash-merge** a `main`.
- **Fuera de alcance:** cascada multi-mes (solo anterior→actual, un paso); fuentes que no sean tarjeta; el
  modelo "real" de gastos ocultos (hoy factor fijo 1.35); persistir el arrastre; cualquier cambio de UI.

---

## 1. Mecánica (alcance acotado)

- **Solo el mes calendario actual** recibe arrastre, y **solo del mes inmediatamente anterior** (un paso, sin
  cascada). "Mes" = el del timeline (bucket por `event_date`).
- Por cada row de **tarjeta** (`source_type = 'tarjeta_credito'`) del **mes anterior**, por **moneda**:
  `saldo = amount − paid_real`. Si `saldo > 0`, se calcula el arrastre (saldo + interés) y se **suma al
  `amount`** de la row de la **misma tarjeta y moneda** del **mes actual** (matcheo por
  `(source_id, currency_id)`).
- Se recomputa `amount_converted` de la row actual (suma `arrastre × cotización` de esa moneda en el
  `event_date` de la row).
- **(a)** El arrastre **sube `pending_expenses`** del mes actual (es deuda que ahora se debe): se suma el
  arrastre convertido al pendiente del mes (y por lo tanto baja el `balance`).
- **Mínimo del mes:** en la row que recibe arrastre se **recomputa `minimum_payment = amount ×
  PROJECTED_MINIMUM_RATE`** (el 15% global, misma constante que el motor) sobre el `amount` ya arrastrado, para
  mostrar el mínimo a pagar del mes. Las rows sin arrastre conservan el `minimum_payment` del motor.
- Las rows del mes anterior (mes pasado → totales en 0, pero **las filas siguen** con sus datos) aportan
  `amount`, `paid_real`, `minimum_payment`, `financing_rate`, `overdue_rate` para el cálculo.
- Si no hay row del mes anterior para esa tarjeta+moneda, o el saldo es ≤ 0, no hay arrastre.

---

## 2. Función de interés (encapsulada)

Módulo nuevo `app/services/cash_flow/interest.py`. Pura, fácil de cambiar a futuro:

```python
from decimal import ROUND_HALF_UP, Decimal
from app.services.cash_flow.constants import HIDDEN_COST_FACTOR  # Decimal("1.35")


def monthly_carry(amount, paid_real, minimum_payment, financing_rate, overdue_rate) -> Decimal:
    """Saldo impago + interés a arrastrar al mes siguiente (misma moneda). 0 si está saldado."""
    balance = amount - paid_real
    if balance <= 0:
        return Decimal("0.00")
    paid_minimum = paid_real >= minimum_payment
    rate = financing_rate if paid_minimum else overdue_rate          # mora si no pagó el mínimo
    interest = balance * (rate / Decimal("100")) / Decimal("12") * HIDDEN_COST_FACTOR
    return (balance + interest).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

- `HIDDEN_COST_FACTOR = Decimal("1.35")` va en `app/services/cash_flow/constants.py` (junto a
  `PROJECTED_MINIMUM_RATE`). El 1.35 modela gastos ocultos; es provisional.
- `minimum_payment` puede ser `None` (rows viejas): tratar `None` como "no alcanza el mínimo" (mora) — o, si
  `minimum_payment is None`, `paid_minimum = False`.

**Ejemplo (Dólar de mayo: amount 578.76, pagó 74, mínimo 93.93 → no pagó el mínimo → mora 18.30):**
`saldo 504.76; interés 504.76 × 0.183 / 12 × 1.35 = 10.39; arrastre = 515.15`. Se suma al Dólar de junio
(0 → 515.15).

---

## 3. Dónde corre (`get_timeline`)

Segunda pasada en `cash_flow_entry_service.get_timeline`, **después** de armar los buckets por mes y **antes**
(o durante) de calcular los agregados del mes:

1. `current_key = today.strftime("%Y-%m")`; `prev_key` = mes calendario anterior.
2. Si existen ambos buckets: indexar las rows de tarjeta del `prev` por `(source_id, currency_id)`.
3. Para cada row de tarjeta del bucket `current`: buscar su par en `prev`; si hay, `carry =
   monthly_carry(prev.amount, prev.paid_real, prev.minimum_payment, prev.financing_rate, prev.overdue_rate)`.
4. Si `carry > 0`: `row.amount += carry`; `row.amount_converted += carry × _rate(currency_id, row.event_date)`;
   `row.minimum_payment = (row.amount × PROJECTED_MINIMUM_RATE).quantize(0.01, HALF_UP)`; y sumar
   `carry_converted` al `pending_expenses` del mes actual.

`MonthEntryOut.amount`/`amount_converted`/`minimum_payment` ya existen; **sin campos nuevos** en el schema. El resto del timeline
(efectivo, arrastre del balance, meses pasados en 0) no cambia.

---

## 4. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow/constants.py` | + `HIDDEN_COST_FACTOR = Decimal("1.35")` |
| `app/services/cash_flow/interest.py` | **nuevo**: `monthly_carry(...)` |
| `app/services/cash_flow_entry_service.py` | 2ª pasada de arrastre en `get_timeline` |
| `tests/test_interest.py` | **nuevo**: unit de `monthly_carry` |
| `tests/test_get_cash_flow_entries.py` | arrastre en el GET (mes actual) |

---

## 5. Tests

**`monthly_carry` (unit):**
- No pagó el mínimo → usa `overdue_rate`. Ej.: `monthly_carry(578.76, 74, 93.93, 14.64, 18.30) == 515.15`.
- Pagó el mínimo pero no todo → usa `financing_rate`.
- Saldado (paid_real ≥ amount) → `0.00`.
- `minimum_payment is None` → trata como mora.

**`get_timeline`:**
- Tarjeta con row del mes anterior parcialmente paga (USD 578.76, pagó 74) y row del mes actual misma moneda →
  el `amount` del mes actual sube por el arrastre (515.15) y el `pending_expenses` del mes actual incluye su
  convertido.
- Mes anterior **saldado** (Peso 4874/4874) → la row del mes actual no cambia.
- Sin row del mes anterior para esa tarjeta+moneda → sin arrastre.
- `today` inyectado para fijar mes actual/anterior.

---

## 6. Plan de implementación (orientativo)

Un slice (`feat/credit-card-carryover-interest`), TDD: unit de `monthly_carry` (rojo→verde) → 2ª pasada en
`get_timeline` con su test → suite verde → cierre (squash-merge). Sin tocar Notion.
