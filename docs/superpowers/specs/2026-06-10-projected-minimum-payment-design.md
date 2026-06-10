# Mínimo de pago proyectado = 15% del amount — Diseño

> Hoy el motor de tarjetas deja `minimum_payment = NULL` en las entries **proyectadas** (cuotas futuras +
> suscripciones), porque no hay resumen emitido del que sacarlo. Pasamos a estimarlo como **15% del amount**.
> El 15% vive en una constante compartida del paquete `cash_flow`, para que el motor lo guarde y el GET del
> timeline (que ya expone `minimum_payment` por row) la reuse en sus cálculos.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice chico: módulo de constante + cambio en la Responsabilidad 2 del motor.
- **Cierre:** rama `feat/projected-minimum-payment`, **squash-merge** a `main`.
- **Fuera de alcance:** los "otros cálculos" del GET con esa constante (vendrán aparte; solo se deja la
  constante disponible); el `minimum_payment` real del último resumen (Resp 1, sin cambios); consolidar el
  `HORIZON` duplicado (está en 5 motores — cleanup separado).

---

## 1. Constante compartida

Nuevo módulo `app/services/cash_flow/constants.py`:

```python
from decimal import Decimal

# Mínimo de pago estimado para los meses PROYECTADOS de tarjeta (no hay resumen emitido): 15% del amount.
PROJECTED_MINIMUM_RATE = Decimal("0.15")
```

Única fuente del 15%. Lo importan el motor (`cash_flow/credit_cards.py`, mismo paquete) y, a futuro, el
service del timeline (`cash_flow_entry_service.py`) para sus cálculos. Este slice **no** modifica el GET.

---

## 2. Motor de tarjetas (Responsabilidad 2 — proyección)

En [credit_cards.py](../../../backend/app/services/cash_flow/credit_cards.py) `materialize_credit_card`, el
bloque de proyección hoy arma cada target con `minimum_payment=None`. Cambia a:

```python
minimum_payment=(amount * PROJECTED_MINIMUM_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
```

- `amount` es el monto **agregado por `(año, mes, moneda)`** que ya calcula `_projection_sums` → el mínimo
  queda en la **misma moneda** de la fila, sin conversión.
- Redondeo a 2 decimales, `ROUND_HALF_UP` (consistente con `effective_rate` / `dial_prorated`).
- Imports nuevos en el motor: `from decimal import ROUND_HALF_UP` (ya importa `Decimal`) y
  `from app.services.cash_flow.constants import PROJECTED_MINIMUM_RATE`.

**Responsabilidad 1 (último resumen): sin cambios.** Sigue guardando el `minimum_payment` real del banco
(`statement.minimum_payment_local` / `_usd`). El 15% es solo para lo proyectado.

---

## 3. Re-materialización

El cambio aplica a **nuevas materializaciones**. Las entries proyectadas **ya guardadas** (con `minimum_payment`
NULL) se actualizan al 15% recién cuando la tarjeta se **re-materialice** (editar tarjeta / promover un resumen,
que ya disparan `materialize_credit_card`). **Sin backfill** ni migración de datos en este slice. El UPSERT de
`_reconcile` actualiza la fila in place al re-materializar, así que se auto-cura con el uso normal.

---

## 4. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow/constants.py` | **nuevo**: `PROJECTED_MINIMUM_RATE` |
| `app/services/cash_flow/credit_cards.py` | Resp 2: `minimum_payment` = 15% del amount (+ imports) |

---

## 5. Tests (`tests/test_cashflow_credit_cards.py`)

- Una entry **proyectada** (cuota futura o suscripción) tiene `minimum_payment == (amount * 0.15)` redondeado a
  2 decimales (verificar en local y USD si el caso lo cubre).
- La entry del **último resumen** (Resp 1) mantiene su `minimum_payment` real del banco (no se pisa con el 15%).

---

## 6. Plan de implementación (orientativo)

Un slice (`feat/projected-minimum-payment`), TDD: test rojo (proyectada con 15%) → crear `constants.py` →
cambiar la Resp 2 del motor → verde → cierre (squash-merge). Sin tocar Notion.
