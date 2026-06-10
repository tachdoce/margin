# timeline — arrastre en cascada del saldo impago de tarjeta — Diseño

> El arrastre de tarjeta deja de ser **un solo paso** (mes anterior → actual) y pasa a ser una **cascada**: por
> cada tarjeta y moneda, el saldo impago de un mes (+interés) se suma al `amount` del mes siguiente, y así hasta
> el horizonte, **mientras exista una row** donde sumarlo. El "pago efectivo" de cada mes = `paid_real` si hay,
> si no el **plan explícito**; si no hay ninguno, es **0** → arrastra todo el `amount` + interés (proyección
> "si no hago nada").

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, `get_timeline` + `monthly_carry`. Read-time.
- **Cierre:** rama `feat/carryover-cascade`, **squash-merge** a `main`.
- **Dependencia:** `feat/carryover-fold-and-hide-zero` (ya en `main`) — este **reemplaza** el arrastre de paso
  único por la cascada.
- **Fuera de alcance:** cambiar cómo el motor genera los `base_amount` (resúmenes/cuotas/rellenos); el modelado
  "real" de gastos ocultos (sigue el factor 1.35).

---

## 1. Modelo de cascada

Por cada **(tarjeta, moneda)**, recorriendo sus rows en orden ascendente de `event_date` (incluye los rellenos
del motor, que existen hasta el horizonte → siempre hay row donde arrastrar):

```
carry_in = 0
para cada row r de la serie (ascendente):
    amount      = r.base_amount + carry_in
    payment     = r.paid_real if r.paid_real > 0 else r.planned_amount   # plan EXPLÍCITO (0 si no hay)
    minimum     = 15% * amount        (si carry_in > 0; si no, el minimum del motor)
    saldo       = max(0, amount - payment)
    tasa        = financing_rate if payment >= minimum else overdue_rate
    interés     = saldo * tasa/100 / 12 * 1.35
    carry_in    = saldo + interés      # para la row siguiente de la serie
```

- **`payment`** usa el **plan explícito** (`r.planned_amount` = suma de pagos planificados del plan, 0 si no
  hay), **no** el fallback a `amount`. Sin plan ni pago ⇒ `payment = 0` ⇒ arrastra todo.
- La cascada **se corta** cuando no hay más rows (último mes = horizonte) o cuando `saldo` llega a 0 (se pagó
  todo).
- Aplica **solo** a rows `tarjeta_credito`. El primer mes de la serie no tiene `carry_in`.

`monthly_carry` se reusa, con el parámetro `paid_real` renombrado a **`payment`** (el cálculo no cambia: balance
= amount − payment; financiación si payment ≥ minimum, si no mora; `(balance+interés).quantize(.01, HALF_UP)`).
Sus tests siguen válidos (pasan el `payment` donde antes iba `paid_real`).

---

## 2. Aplicación en `get_timeline`

Reemplaza el paso único (`prev_cards` + `if key == current_key`) por una **pre-pasada de cascada**:

1. Agrupar las rows crudas (del `_TIMELINE_SQL`) por `(source_id, currency_id)` para `tarjeta_credito`, ordenadas
   por `event_date`.
2. Recorrer cada serie con el modelo de §1, guardando por `row.id`: `carry_in` (lo que se suma a esa row) y el
   `minimum` resultante.
3. En el armado de las rows (loop existente): para una row de tarjeta, `amount += carry_in[id]`,
   `amount_converted += carry_in[id] * _rate(moneda, event_date)`, `minimum_payment = minimum[id]`. Luego el
   `_effective_planned` y el `pending` se calculan sobre ese `amount` (igual que hoy).

`planned_amount` (lo que se muestra) sigue el fallback de siempre: plan explícito, o `amount` si no hay
(intención de pagar todo). Es independiente del `payment` del carry (que usa el plan explícito o 0).

---

## 3. Lo que se mantiene

- **Ocultar `amount == 0`**: igual (filtro de salida). Con la cascada, una serie con saldo impago hace que
  **todos** sus meses futuros tengan `amount > 0` → se vuelven visibles (el snowball se ve hasta el horizonte).
- **`minimum_payment`** recomputado al 15% en cada mes con arrastre.
- **`pending`/totales**: `pending = efectivo − pagado` por row; el `amount` arrastrado entra naturalmente.
- **Persistencia**: nada se persiste; todo read-time.

---

## 4. Consecuencias asumidas

- **Proyección "si no hago nada"**: sin pagos ni planes, el saldo de cada tarjeta crece mes a mes con interés
  hasta el horizonte (números grandes, a propósito). Planificar/pagar lo reduce.
- **No se valida doble conteo** entre `base_amount` (cuotas/resúmenes del motor) y el arrastre; se asume que el
  `base_amount` de cada mes es el cargo nuevo de ese mes y el arrastre es lo impago del anterior. (Validable con
  las tablas de datos reales.)

---

## 5. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow/interest.py` | `monthly_carry`: `paid_real` → `payment` (semántico; cálculo igual) |
| `app/services/cash_flow_entry_service.py` | pre-pasada de cascada por serie (reemplaza el paso único); aplicar `carry_in`/`minimum` por row |
| `tests/test_get_cash_flow_entries.py` | cascada multi-mes; mes sin plan arrastra todo; con plan parcial arrastra el resto; corte al saldar |

---

## 6. Tests

- **Cascada 2 pasos:** serie con saldo impago en M y sin plan en M+1 → M+1 arrastra todo (amount M+1) y M+2
  recibe (amount M+1 + interés). Verifica el encadenado.
- **Plan parcial frena parte:** un mes con plan explícito < amount → arrastra solo `amount − plan` (+interés);
  el mínimo decide financiación/mora.
- **Sin plan ni pago → arrastra todo:** `payment = 0` ⇒ `saldo = amount` ⇒ el mes siguiente recibe
  `amount + interés` (mora, porque 0 < mínimo).
- **Se salda → corta:** si `payment ≥ amount`, `carry = 0` y los meses siguientes no reciben arrastre de esa
  serie (vuelven a ocultarse si quedan en 0).
- **Unit `monthly_carry`:** sin cambios de valores (rename de parámetro).

---

## 7. Plan (orientativo)

Un slice (`feat/carryover-cascade`), TDD: tests de cascada (rojo) → `monthly_carry` (rename) + pre-pasada de
cascada en `get_timeline` (reemplaza el paso único) → suite verde → cierre (squash-merge). Sin tocar Notion.
