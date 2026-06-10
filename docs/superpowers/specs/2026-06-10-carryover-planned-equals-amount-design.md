# timeline — la row arrastrada lleva planned_amount = amount — Diseño

> En el arrastre de tarjeta (saldo impago + interés del mes anterior → mes actual), la row que recibe el
> arrastre debe quedar con **`planned_amount = amount`** (y su convertido). Así la deuda arrastrada entra en la
> misma semántica que el resto del timeline: **sin planificado, la intención es pagar la totalidad**; y si el
> presupuesto no alcanza, el usuario puede **planificar pagar solo una parte** (crear un pago planificado), que
> baja el planned a esa parte.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, retoque del slice de arrastre: 2 líneas en `_apply_card_carryover` + asserts.
- **Cierre:** rama `feat/carryover-planned-equals-amount`, **squash-merge** a `main`.
- **Dependencia:** `feat/credit-card-carryover-interest` (ya en `main`).
- **Fuera de alcance:** la mecánica de planificar el pago parcial en sí (ya existe vía `cash_flow_payments`);
  cambios de totales.

---

## 1. Cambio

En [cash_flow_entry_service.py](../../../backend/app/services/cash_flow_entry_service.py)
`_apply_card_carryover`, para cada row que recibe arrastre (`carry > 0`), tras subir `amount` /
`amount_converted` / `minimum_payment`, **igualar el planificado al monto**:

```python
        row.planned_amount = row.amount
        row.planned_amount_converted = row.amount_converted
```

---

## 2. Rationale (semántica del timeline)

`_effective_planned` ya define: si la row **no** tiene pago planificado, el "planificado efectivo" cae al
`amount` → la intención es pagar todo. La row arrastrada (un 0-fill que pasó a, p. ej., 515.15) debe seguir esa
regla: `planned_amount = amount` = pagar la deuda arrastrada entera por defecto. Si el usuario ve que el mes no
cierra, **planifica** pagar solo una parte (un `cash_flow_payment` del plan), y entonces el planned refleja esa
parte — igual que cualquier otra row.

---

## 3. Totales (sin cambio)

`pending_expenses` ya se ajustó en la pasada (se sumó el arrastre convertido a `pe`). Este cambio solo deja
**consistente el campo `planned_amount`** de la row con su `amount`; no recalcula ni duplica totales.

---

## 4. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow_entry_service.py` | `_apply_card_carryover`: `planned_amount`/`planned_amount_converted` = `amount`/`amount_converted` |
| `tests/test_get_cash_flow_entries.py` | asserts en `test_carryover_adds_prev_unpaid_to_current_month` |

---

## 5. Tests

En `test_carryover_adds_prev_unpaid_to_current_month` (Peso, cotiza x1, arrastre 810.80):
- `row.planned_amount == Decimal("810.80")` (= amount).
- `row.planned_amount_converted == row.amount_converted`.

---

## 6. Plan (orientativo)

Un slice (`feat/carryover-planned-equals-amount`), TDD: sumar los asserts (rojo) → las 2 líneas en
`_apply_card_carryover` (verde) → suite → cierre (squash-merge). Sin tocar Notion.
