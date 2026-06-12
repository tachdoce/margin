# Timeline: interés generado, mes de deuda sana y mes de objetivo

Fecha: 2026-06-12
Estado: aprobado (diseño)

## Problema

`get_timeline` hoy devuelve `TimelineOut = { months[], open_debts[] }` y cada
`MonthOut` tiene `available, pending_income, pending_expenses,
remaining_spending, balance` (+ las filas). No expone:

1. Cuánto **interés** te genera cada mes el no pagar las deudas completas.
2. En qué mes pasás de **deuda punitiva** a **deuda sana**.
3. Si cargaste un **objetivo**, en qué mes lo cumplís.

Este spec agrega esas tres salidas, derivadas todas del mismo concepto de interés
por pago parcial. **Solo tarjetas** (las únicas que arrastran interés hoy);
extender el arrastre a deudas no-tarjeta es otro spec (Spec B).

## Conceptos

- **Interés generado en un mes:** el interés (en moneda local) que ese mes suma
  al carry por no pagar las tarjetas completas. Es el mismo interés que ya
  calcula la cascada de carry del timeline, hoy oculto dentro de `monthly_carry`.
- **Deuda sana:** sostenés los pagos sin generar interés punitivo. Operacional:
  un mes es "sano" cuando su interés generado es 0.
- **Deuda punitiva:** lo opuesto — generás interés por no cubrir las deudas.

## Salida 1 — `generated_interest` (por mes)

Campo nuevo en `MonthOut`: `generated_interest: Decimal`, en **moneda local**
(convertido, como los demás totales del mes).

**Definición:** suma, sobre **todas las tarjetas** del usuario, del interés que
ese mes se genera por pago parcial:

```
interés_fila = (amount − pago) × (tasa/100) / 12 × HIDDEN_COST_FACTOR
```

donde, igual que `monthly_carry`:
- `amount` = monto de la fila + carry entrante.
- `pago` = planificado del plan si > 0; si no, real si > 0; si no, `amount`
  (sin plan ni real, el timeline asume pago total → sin interés).
- `tasa` = `financing_rate` si `pago ≥ minimum` (mínimo recalculado 15% si hubo
  carry), si no `overdue_rate` (mora).
- `HIDDEN_COST_FACTOR = 1.35` (incluido: es el interés que realmente se suma).
- Si `amount − pago ≤ 0` → 0.

Se convierte a pesos con la cotización del mes de la fila y se **acumula por
mes**, atribuido al mes que lo generó. **Meses pasados → 0** (como el resto de
los totales del histórico).

### Implementación

- **`interest.py`:** extraer la fórmula a `_raw_interest(amount, payment,
  minimum_payment, financing_rate, overdue_rate) -> Decimal` (sin cuantizar) y
  agregar `monthly_interest(...)` (la devuelve cuantizada a 0.01). `monthly_carry`
  se reescribe como `balance + _raw_interest(...)` cuantizado — **idéntico en
  comportamiento** (no cambia lo que ve el PlanningEngine).
- **`get_timeline`** (`cash_flow_entry_service.py`): en la cascada de carry por
  `(tarjeta, moneda)` (~líneas 188-204), acumular
  `gen_interest[mes] += monthly_interest(...) × _rate(currency_id, event_date)`.
  Al armar cada `MonthOut`, setear `generated_interest` desde ese acumulado
  (0 para meses pasados).

## Salida 2 — `healthy_debt_month` (top-level)

Campo nuevo en `TimelineOut`: `healthy_debt_month: str | None` (`"YYYY-MM"`).

**Definición:** el **mes después del último mes con `generated_interest > 0`**
(primer 0 que se queda en 0). Sobre los meses **activos** (≥ mes actual):

- Si hay meses con `generated_interest > 0`: tomar el último; el resultado es el
  mes siguiente.
  - Si ese "mes siguiente" cae **fuera del horizonte** (el último mes con interés
    es el último del timeline) → `null` (en el horizonte nunca te estabilizás).
- Si **ningún** mes activo tiene interés (`generated_interest = 0` en todos) →
  el **primer mes activo** (ya estás sano desde el arranque).

## Salida 3 — `goal_reached_month` (top-level)

Campo nuevo en `TimelineOut`: `goal_reached_month: str | None` (`"YYYY-MM"`).

**Definición:** el **primer mes activo `M`** tal que:
- `M ≥ healthy_debt_month` (y `healthy_debt_month` no es null), **y**
- `balance[M] ≥ objetivo_local`.

donde `objetivo_local = plan.goal_amount × _rate(plan.goal_currency_id, today)`
(el `balance` está en pesos; el objetivo se convierte a pesos con la cotización
de hoy → umbral fijo; si el objetivo ya es en pesos, sin conversión).

**Bordes (→ `null`):**
- El plan no tiene objetivo (`goal_amount` o `goal_currency_id` null).
- `healthy_debt_month` es null (nunca llegás a deuda sana).
- Ningún mes que cumpla deuda-sana alcanza el objetivo en el horizonte.

## Schemas

`app/schemas/cash_flow_entry.py`:
- `MonthOut`: agregar `generated_interest: Decimal`.
- `TimelineOut`: agregar `healthy_debt_month: str | None` y
  `goal_reached_month: str | None`.

Son campos nuevos en la respuesta → compatible hacia atrás para la app.

## Orden de cálculo en `get_timeline`

1. (ya existe) Cascada de carry → ahora también acumula `generated_interest` por
   mes.
2. (ya existe) Armado de `months[]` con balances → cada `MonthOut` lleva su
   `generated_interest`.
3. **Nuevo, al final:** con la lista de meses ya construida, derivar
   `healthy_debt_month` (de la serie de `generated_interest`) y luego
   `goal_reached_month` (de los `balance` + el objetivo del plan +
   `healthy_debt_month`). Devolver en `TimelineOut`.

`get_timeline` ya recibe `plan_id`; el objetivo se lee del `Plan`
(`goal_amount`, `goal_currency_id`).

## Tests

`tests/test_get_cash_flow_entries.py` (o el de timeline):

**`generated_interest`:**
1. Tarjeta pagada entera (sin plan/real) → 0 en su mes.
2. Tarjeta con pago planificado parcial ≥ mínimo → interés con `financing_rate`
   (× 1.35), en pesos, en ese mes.
3. Pago < mínimo → interés con `overdue_rate` (mora).
4. Tarjeta en USD → interés convertido a pesos.
5. Varias tarjetas → suma en el mes.
6. Mes pasado → 0.
7. `monthly_carry` sigue devolviendo lo mismo que antes (test de no-regresión del
   refactor).

**`healthy_debt_month`:**
8. Serie con interés en M..M+k y 0 después → resultado = M+k+1.
9. Interés hasta el último mes del horizonte → `null`.
10. Sin interés en ningún mes → primer mes activo.

**`goal_reached_month`:**
11. Objetivo alcanzable después de la deuda sana → primer mes con
    `balance ≥ objetivo` y `≥ healthy_debt_month`.
12. `balance ≥ objetivo` pero **antes** de `healthy_debt_month` → no cuenta;
    devuelve el primer mes válido posterior (o null).
13. Sin objetivo en el plan → `null`.
14. `healthy_debt_month` null → `null`.
15. Objetivo en USD → se convierte a pesos para comparar.

## Touchpoints

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow/interest.py` | `_raw_interest` + `monthly_interest`; `monthly_carry` reescrito sin cambiar su salida |
| `app/services/cash_flow_entry_service.py` | acumular `generated_interest` en la cascada; setearlo en `MonthOut`; derivar `healthy_debt_month` y `goal_reached_month`; devolverlos |
| `app/schemas/cash_flow_entry.py` | `generated_interest` en `MonthOut`; `healthy_debt_month`, `goal_reached_month` en `TimelineOut` |
| `tests/test_get_cash_flow_entries.py` | tests de las tres salidas |

## Fuera de alcance (YAGNI)

- Que las deudas **no-tarjeta** (préstamo/deuda/tarjetazo) arrastren interés por
  pago parcial y entren en `generated_interest` (**Spec B** — cambia proyecciones
  y toca el PlanningEngine).
- La señal de viabilidad "todos los meses con `balance ≥ 0`" (se decidió dejarla
  fuera por ahora).
- Más tipos de objetivo además de `ahorro_total`.
