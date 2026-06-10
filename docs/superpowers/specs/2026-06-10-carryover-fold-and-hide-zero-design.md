# timeline — plegar el arrastre en el loop + ocultar rows en 0 — Diseño

> Dos cambios sobre el arrastre de tarjeta del mes actual, en `get_timeline`:
> **(A)** plegar el cálculo del arrastre **dentro del loop de filas** (en vez del post-paso
> `_apply_card_carryover`), para que el `amount` arrastrado pase por la misma semántica que el resto
> (`_effective_planned`: sin plan → se paga la totalidad; con plan parcial → esa parte), sin contar doble el
> pendiente; y **(B)** tras aplicar el arrastre, **ocultar de la respuesta** todas las rows con `amount == 0`
> (las que el arrastre "rescató" ya no son 0 y quedan). Refactor que deja el slice de arrastre prolijo.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, `get_timeline` (+ helper `_effective_planned`). Read-time.
- **Cierre:** rama `feat/carryover-fold-and-hide-zero`, **squash-merge** a `main`.
- **Dependencia:** `feat/credit-card-carryover-interest` (ya en `main`) — este refactor **reemplaza** su
  post-paso `_apply_card_carryover`.
- **Fuera de alcance:** el relleno del motor (sigue persistiendo las rows en 0 como base para devengar; acá solo
  se **ocultan en el GET**); ocultar meses sin rows (se muestran con su balance).

---

## 1. Parte A — plegar el arrastre en el loop

Hoy `get_timeline` arma las rows con `_effective_planned(r)` en el loop y, en un **post-paso**
(`_apply_card_carryover`), suma el arrastre al `amount` y al `pending` (`pe`) del mes. Eso tiene dos problemas
al permitir **planificar un pago parcial** de la deuda arrastrada:

1. Pisaría / no respetaría el plan parcial.
2. Contaría doble el pendiente (el plan parcial en el loop + el arrastre en `pe`).

**Cambio:** sumar el `carry` al `amount` (y `amount_converted`) **dentro del loop**, **antes** de derivar el
efectivo/pendiente. Entonces:

- `_effective_planned` decide solo: si la row **no** tiene plan → `planned = amount` (ya con el arrastre, =
  pagar la deuda entera); si tiene plan parcial → `planned` = esa parte.
- `pending = efectivo − pagado` queda bien en ambos casos (sin sumar a `pe` a mano).
- `minimum_payment` se recomputa al **15%** (`PROJECTED_MINIMUM_RATE`) del `amount` ya arrastrado.

Se **elimina** `_apply_card_carryover` y el ajuste manual de `pe`.

`_effective_planned` se refactoriza para tomar los montos explícitos (así se le pasa el `amount` ya arrastrado):

```python
def _effective_planned(planned_amount, planned_amount_converted, amount, amount_converted):
    if planned_amount > 0:
        return planned_amount, planned_amount_converted
    return amount, amount_converted
```

El arrastre se calcula como hoy: `monthly_carry(prev.amount, prev.paid_real, prev.minimum_payment,
prev.financing_rate, prev.overdue_rate)` del par `(source_id, currency_id)` del **mes calendario anterior**,
solo para rows `tarjeta_credito` del **mes actual**. `carry_converted = carry × _rate(currency, event_date)`.

---

## 2. Parte B — ocultar las rows con amount 0

**Después** de armar los meses (con el arrastre ya aplicado), filtrar de la respuesta toda row con
`amount == 0`:

- En cada mes: `incomes` y `expenses` se quedan solo con `amount != 0`.
- `open_debts`: también se filtran las de `amount == 0`.
- **Totales sin cambio:** una row en 0 aporta 0 a `pending_*` (su efectivo y pagado son 0), así que filtrarla no
  altera `pending_income`/`pending_expenses`/`balance`. Es un filtro de **presentación**.
- **Persistencia:** las rows en 0 **siguen en la DB** (el relleno del motor es la base para devengar en
  iteraciones futuras); acá solo no se devuelven.
- **Meses sin rows:** un mes cuyas rows quedaron todas en 0 **se muestra igual** (con `available` /
  `remaining_spending` / `balance`; el arrastre del saldo encadena entre meses sin cambio).
- **Orden:** arrastre primero (rescata las rows que pasan a > 0), filtro al final.

> Nota: con los datos actuales, las únicas rows en `amount 0` son los rellenos del motor (sin plan ni pago), así
> que el filtro `amount == 0` es seguro. Si en el futuro hubiera un plan/pago sobre una row de monto 0, se
> revisaría el criterio.

---

## 3. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow_entry_service.py` | plegar arrastre en el loop; `_effective_planned` con args explícitos; eliminar `_apply_card_carryover`; filtrar `amount == 0` en meses y `open_debts` |
| `tests/test_get_cash_flow_entries.py` | `planned_amount == amount` en la row arrastrada; ajustar el test de "prev saldado" (la row en 0 ya no aparece); test del filtro de 0 |

---

## 4. Tests

- **Arrastre (adds):** prev parcial → row del mes actual con `amount` y `planned_amount` = arrastre (810.80),
  `planned_amount_converted == amount_converted`, `minimum_payment == 121.62`, `pending_expenses == 810.80`.
- **Prev saldado:** sin arrastre → la row del mes actual queda en 0 → **no aparece** en `expenses` (filtrada).
- **Plan parcial sobre la row arrastrada:** si hay un pago planificado parcial, `planned_amount` = esa parte (no
  el amount) y `pending_expenses` no cuenta doble.
- **Filtro de 0:** una row de relleno (amount 0, sin arrastre) no aparece en la respuesta; el mes con solo
  rellenos se muestra sin rows pero con su balance; una `open_debt` en 0 se filtra.

---

## 5. Plan (orientativo)

Un slice (`feat/carryover-fold-and-hide-zero`), TDD: tests (planned=amount, prev-saldado-oculto, filtro 0) →
plegar el arrastre en el loop + `_effective_planned` explícito + eliminar el post-paso → filtro de `amount==0` →
suite verde → cierre (squash-merge). Sin tocar Notion.
