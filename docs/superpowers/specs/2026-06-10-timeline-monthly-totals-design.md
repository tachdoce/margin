# timeline — totales mensuales (efectivo, pendientes, saldo) — Diseño

> El `GET /cash-flow-entries` (timeline) deja de exponer totales "brutos" y pasa a una vista de **decisión**:
> por cada mes muestra el efectivo disponible, lo que falta cobrar/pagar, el gasto discrecional restante y el
> saldo de fin de mes que se arrastra al mes siguiente. Sirve para que el usuario (o, a futuro, el PlanEngine)
> vea cuándo un mes no cierra y difiera pagos hasta llevar el saldo a positivo.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice. Toca **solo** `get_timeline` + el schema `MonthOut`. Nada persistido
  (todo derivado en read).
- **Cierre:** rama `feat/timeline-monthly-totals`, **squash-merge** a `main`.
- **Dependencia:** `cash_balances` (tabla + `holdable_currencies`) ya mergeado en `main` ✓.
- **Fuera de alcance:** el PlanEngine que ajusta pagos para llegar a positivo; cualquier cambio al SQL de
  entries, a los pagos, o al endpoint `by-source`/PATCH.

---

## 1. Punto de partida

`get_timeline(db, user, plan_id)` ([cash_flow_entry_service.py](../../../backend/app/services/cash_flow_entry_service.py))
arma, a partir de `_TIMELINE_SQL`, una lista de `MonthOut` (meses con `incomes`/`expenses` y totales) más
`open_debts` (rows sin `event_date`). Hoy cada row trae `amount`, `paid_real`, `planned_amount` y sus
`*_converted` (a moneda de curso legal vía `currency_rates`). Los totales del mes
(`total_income`/`total_expenses`/`balance`) suman `amount_converted`.

Este diseño NO toca el SQL ni el router. Cambia la lógica Python de `get_timeline` y el schema `MonthOut`.
`get_timeline` suma un parámetro **`today: date | None = None`** (default `date.today()`), igual que
`list_by_source`, para tests deterministas.

---

## 2. Parte 1 — `planned_amount` efectivo por row

Para cada row **con `event_date`** (ingresos y egresos por igual), antes de armar los totales:

- `planned_amount > 0` → queda igual (suma de pagos planificados del plan).
- `planned_amount == 0` → `planned_amount = amount` y `planned_amount_converted = amount_converted`.

Las `open_debts` (sin `event_date`) **no** reciben el fallback: quedan tal cual hoy.

El campo sigue llamándose `planned_amount` (se pisa el valor). `amount` y `paid_real` quedan intactos.

**Rationale:** un usuario que va a pagar el monto total de algo (ej. alquiler) no crea un pago planificado por
ese total; "sin planificado" se interpreta como "voy a pagar el proyectado".

---

## 3. Parte 2 — totales pendientes

Por cada row con `event_date`: `pendiente = planned_amount_efectivo − paid_real` (usando los `*_converted`;
sin piso, puede dar negativo si hubo sobrepago).

- `pending_income` = Σ pendiente de los ingresos del mes (antes `total_income`).
- `pending_expenses` = Σ pendiente de los egresos del mes (antes `total_expenses`).

"Pendiente" = lo que falta cobrar (ingresos) o pagar (egresos), neto de lo ya cobrado/pagado real.

---

## 4. Parte 3 — efectivo, gasto restante y saldo acumulado

Tres conceptos nuevos por mes. Los meses se recorren en orden ascendente (`months[]` ya viene ordenado).

**`available` (disponible):**
- **Mes 1** (mes calendario actual = primer mes de `months[]`, garantizado por el piso del engine = primer día
  del mes actual): `available = Σ (cash_balances.amount × cotización_de_hoy)` sobre las filas de
  `cash_balances` del usuario. Cotización = `currency_rates.value` con `rate_date = today` (`COALESCE(.,1)`
  para curso legal / sin cotización).
- **Meses 2+:** `available[N] = balance[N-1]` (lo que sobró del mes anterior).

**`remaining_spending` (gasto mensual restante):** sale del `dial` del plan
(`plan.dial_amount` convertido a curso legal: `× cotización_de_hoy` de `plan.dial_currency_id`, `COALESCE 1`).
- **Mes 1:** `remaining_spending = (días_del_mes − (today.day − 1)) / días_del_mes × dial_convertido`,
  cuantizado a 2 decimales. (`today.day` incluido como día restante.)
- **Meses 2+:** `remaining_spending = dial_convertido`.

> **Iteraciones futuras (decisión explícita del usuario):** la fórmula de `remaining_spending` del **primer
> mes** (prorrateo lineal por días restantes) es **provisional / primera aproximación** y **cambiará en
> futuras iteraciones**. Es un placeholder; la lógica definitiva se redefinirá más adelante.

**`balance` (saldo de fin de mes, redefinido):**
```
balance = (available + pending_income) − (pending_expenses + remaining_spending)
```
Deja de ser el flujo (`income − expenses`) y pasa a ser la plata al cierre del mes. Se arrastra:
`available[N] = balance[N-1]`.

---

## 5. Schema (`app/schemas/cash_flow_entry.py`)

`MonthOut` — orden de campos:

```python
class MonthOut(BaseModel):
    month: str
    available: Decimal           # nuevo
    pending_income: Decimal      # antes total_income
    pending_expenses: Decimal    # antes total_expenses
    remaining_spending: Decimal  # nuevo
    balance: Decimal             # redefinido (saldo acumulado)
    incomes: list[MonthEntryOut]
    expenses: list[MonthEntryOut]
```

`TimelineEntryOut`/`MonthEntryOut` (las rows) **no cambian**: siguen exponiendo `amount`, `paid_real`,
`planned_amount` (ahora efectivo) y los `*_converted`. Sin campos nuevos por row.

---

## 6. Cambios de contrato (la web/app debe ajustar)

- `MonthOut.total_income` → `pending_income`; `MonthOut.total_expenses` → `pending_expenses`.
- `MonthOut.balance`: mismo nombre, **semántica nueva** (flujo → saldo de fin de mes acumulado).
- `MonthOut`: + `available`, + `remaining_spending`.
- Row `planned_amount`: mismo nombre, **semántica nueva** ("planificado, o proyectado si no hay plan").

---

## 7. Ejemplo validado (datos reales, usuario `5309521d…`, plan "Estabilización")

| Mes | available | pending_income | pending_expenses | remaining_spending | balance |
|---|---:|---:|---:|---:|---:|
| 2026-06 | 43.666,00 | 90.000,00 | 91.225,70 | 29.400,00 | 13.040,30 |
| 2026-07 | 13.040,30 | 151.100,00 | 129.909,14 | 42.000,00 | −7.768,84 |
| 2026-08 | −7.768,84 | 191.100,00 | 112.110,21 | 42.000,00 | 29.220,95 |

(Disponible mes 1 = Peso 38.500 + U$S 126 × 41. Dial = 42.000 en Peso; junio prorrateado 21/30.)
Julio cierra negativo → señal de que hay que diferir pagos / recortar dial ese mes.

---

## 8. Tests (`tests/test_get_cash_flow_entries.py`)

Inyectar `today` para determinismo. Sembrar `cash_balances` + `currency_rates` + un plan con `dial_amount`.

- **Parte 1:** row con planificado (queda); row sin planificado → toma `amount` (ingreso y egreso);
  `open_debt` sin fallback.
- **Parte 2:** `pending_income`/`pending_expenses` = Σ (efectivo − `paid_real`), incluido un mes con pagos
  reales (verifica el neto).
- **Parte 3:** `available` mes 1 desde `cash_balances` convertido a `today`; arrastre `available[N] =
  balance[N-1]`; `remaining_spending` prorrateado mes 1 y completo mes 2+; `balance = (available +
  pending_income) − (pending_expenses + remaining_spending)`.
- **Nombres:** la respuesta expone `pending_income`/`pending_expenses`/`available`/`remaining_spending`.

---

## 9. Plan de implementación (orientativo)

Un slice (`feat/timeline-monthly-totals`), TDD: tests rojos del nuevo `MonthOut` → `today` param + parte 1
(efectivo) → parte 2 (pendientes) → parte 3 (available/dial/balance) + schema → suite verde → cierre
(squash-merge). Sin tocar Notion.
