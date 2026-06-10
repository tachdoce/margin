# timeline — `available` ancla en el mes actual — Diseño

> En `GET /cash-flow-entries`, el `available` (efectivo) y el arrastre del `balance` se anclan hoy en
> `months[0]` (el primer mes de la lista), asumiendo que ese es el mes actual. Pero si el timeline tiene
> **meses pasados** (p.ej. una cuota o resumen vencido), `months[0]` es un mes pasado y el efectivo se pone ahí
> y se arrastra hacia adelante — incorrecto. El efectivo de hoy debe anclarse en el **mes calendario actual**.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** backend; **solo** `get_timeline` (`app/services/cash_flow_entry_service.py`) + tests. Sin schema
  nuevo, sin migración, sin web (los campos de `MonthOut` no cambian; cambia cómo se calculan).
- **Cierre:** rama `feat/timeline-available-anchor`, **squash-merge** a `main`.

---

## 1. Problema

`get_timeline` arma `months[]` ordenado ascendente y trata `i == 0` (el primer mes) como "mes 1": le pone
`available = efectivo de hoy` y `remaining_spending = dial prorrateado`, y arrastra el `balance` hacia los
meses siguientes. El supuesto era "`months[0]` == mes actual", garantizado por el piso del motor. Pero el
timeline **puede** incluir meses pasados (entries con `event_date` en un mes anterior al actual: vencidos,
data previa). En ese caso el efectivo se ancla en un mes pasado y se arrastra mal.

---

## 2. Regla nueva

El ancla del efectivo y del arrastre es el **mes calendario actual**: `mes_actual = today.strftime("%Y-%m")`
(`today` ya es parámetro de `get_timeline`, default `date.today()`).

Recorriendo `months[]` en orden ascendente:

- **Mes pasado** (`key < mes_actual`): histórico. Los **5 totales** del mes van en **0**:
  `available = pending_income = pending_expenses = remaining_spending = balance = 0`. **No** entra en el
  arrastre (no actualiza el balance previo). Las rows (`incomes`/`expenses`) **se siguen mostrando** tal cual;
  solo se zeran los agregados del mes.
- **Ancla** = el **primer mes con `key >= mes_actual`**: `available = Σ(cash_balances × cotización_de_hoy)`
  (`_available_now`). `remaining_spending = dial_prorrateado` si `key == mes_actual` (el ancla es el mes
  actual), o `dial` completo si el mes actual no tiene entries y el ancla cae en un mes **futuro**.
- **Meses después del ancla:** `available = balance del mes previo` (arrastre), `remaining_spending = dial`
  completo.
- En el ancla y los siguientes: `balance = (available + pending_income) − (pending_expenses + remaining_spending)`,
  y ese `balance` se arrastra.

> **Caso degenerado:** si **todos** los meses son pasados (no hay ninguno `>= mes_actual`), el efectivo no se
> muestra en ningún mes. Fuera de alcance (no se sintetiza un mes actual vacío).

**Implementación (boceto):**
```python
current_key = today.strftime("%Y-%m")
prev_balance = None
for key in sorted(buckets):
    b = buckets[key]
    # sort incomes/expenses (igual que hoy)
    if key < current_key:
        available = pi = pe = remaining_spending = balance = Decimal("0")
    else:
        if prev_balance is None:               # primer mes >= actual = ancla
            available = _available_now(db, user, today)
            remaining_spending = dial_prorated if key == current_key else dial
        else:                                  # meses siguientes
            available = prev_balance
            remaining_spending = dial
        pi, pe = b["pi"], b["pe"]
        balance = (available + pi) - (pe + remaining_spending)
        prev_balance = balance
    months.append(MonthOut(month=key, available=available, pending_income=pi, pending_expenses=pe,
                           remaining_spending=remaining_spending, balance=balance,
                           incomes=b["incomes"], expenses=b["expenses"]))
```
(Para los meses pasados, `pi`/`pe` se fuerzan a `0` aunque `b["pi"]`/`b["pe"]` tengan valor.)

---

## 3. Tests (`tests/test_get_cash_flow_entries.py`)

- **Mes pasado zerado:** con `today` fijo, una entry en un mes anterior → ese mes tiene
  `available/pending_income/pending_expenses/remaining_spending/balance == 0`, y **no** arrastra; el mes actual
  arranca con `available = efectivo de hoy` (no contaminado por el pasado). Verifica que las rows del mes
  pasado igual aparecen.
- **Ancla en el mes actual:** ya cubierto por `test_available_dial_and_balance_first_month` (today = mes de las
  entries).
- **Determinismo:** los tests que asertan **totales del mes** contra el endpoint HTTP usan `date.today()` real
  → al zerar pasados se vuelven sensibles a la fecha de corrida. Pasarlos a llamar
  `svc.get_timeline(db, user, plan_id, today=<fecha fija>)` para fijar el mes actual. Afecta sobre todo a
  `test_timeline_groups_by_month_and_flow` (y cualquiera que asierta `balance`/`pending_*` del mes vía el
  endpoint).

---

## 4. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow_entry_service.py` | `get_timeline`: ancla = mes actual; pasados en 0 sin arrastre |
| `tests/test_get_cash_flow_entries.py` | test de mes pasado zerado; fijar `today` en los tests de totales |

---

## 5. Plan (orientativo)

Un slice (`feat/timeline-available-anchor`), TDD: test de mes pasado (rojo) → cambiar el armado de meses
(ancla = mes actual, pasados en 0) → ajustar los tests de totales para inyectar `today` → suite verde →
cierre. Sin Notion.
