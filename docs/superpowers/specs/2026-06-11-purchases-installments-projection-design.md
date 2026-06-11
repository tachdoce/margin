# purchases — cuotas y proyección en el CashFlowEngine — Diseño

> Las compras con tarjeta de `purchases` ganan cantidad de cuotas (`total_installments`, NULL = 1) y
> alimentan la proyección del CashFlowEngine: toda compra con `purchase_date` posterior al `closing_date`
> del último resumen de su tarjeta proyecta sus cuotas desde M+1, junto a los ítems del resumen. Crear,
> editar o borrar una compra con tarjeta re-materializa las entries de esa tarjeta. Las compras en
> efectivo no tocan ninguna tarjeta ni entran a la proyección.

- **Fecha:** 2026-06-11
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice: columna + validaciones + proyección + disparadores.
- **Cierre:** rama `feat/purchases-projection`, **squash-merge** a `main`.
- **Dependencias (ya en `main`):** tablas `purchases`/`purchase_categories` + CRUD `/purchases` ✓;
  `materialize_credit_card` (Responsabilidades 1 y 2) en `app/services/cash_flow/credit_cards.py` ✓.
- **Fuera de alcance:** tarjetas **sin ningún resumen** no proyectan compras (gate actual de la
  Responsabilidad 2 sin cambios); la categoría `suscripciones` de una compra **no** recurre mensualmente
  (solo cuotas explícitas); cambios en la web.

---

## 1. Columna `purchases.total_installments`

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `total_installments` | smallint | **Sí** | cantidad de cuotas; **NULL = 1 = contado**. Mismo nombre que en `credit_card_purchases` |

Migración aditiva (`add_column`), sin tocar filas existentes. **Semántica de `amount` con cuotas: es el
valor de cada cuota**, no el total de la compra (igual que `credit_card_statement_items.amount`); el total
pagado es `amount × cuotas`.

**Validaciones (POST y PATCH, sobre valores finales con el patrón `final()` existente):**

- Presente y no null → **≥ 1**; si no → `installments_invalid` (código existente).
- Valor final **> 1** con `credit_card_id` final null → `installments_invalid` (cuotas son de tarjeta;
  cubre el PATCH que pasa a efectivo una compra con cuotas: hay que mandar `total_installments: null`
  en el mismo body o rechaza).
- `total_installments: 1` explícito se acepta siempre (equivale a null), incluso en efectivo. Se guarda
  tal cual viene (1 o null), **sin normalizar**.
- En PATCH, null explícito es válido (vuelve a contado): **no** entra en `_NOT_NULLABLE`. Se suma a
  `_EDITABLE`.

**Schemas (`app/schemas/purchase.py`):** `total_installments: int | None = None` en `PurchaseCreate` y
`PurchaseUpdate`; se agrega a `PurchaseOut` y a su `from_model`.

---

## 2. Engine: compras post-cierre en la proyección

En `materialize_credit_card` (`app/services/cash_flow/credit_cards.py`), Responsabilidad 2 — **solo si hay
resumen**, como hoy:

- Helper nuevo `_purchase_sums(db, card, statement, horizon)` → mismo shape que `_projection_sums`:
  `{(year, month, currency_id): monto}`.
  - Selecciona `Purchase` con `credit_card_id == card.id` y `purchase_date > statement.closing_date`.
  - Cada compra aporta `amount` en los meses `k = 1..n` desde el mes del cierre, con
    `n = total_installments or 1` — primera cuota en **M+1**. Ejemplo acordado: cierre 2026-06-01 →
    toda compra con fecha ≥ 2026-06-02 arranca en el estado de julio.
  - Mismo tope de horizonte que los ítems (reusa la lógica de `add()` / `_add_months`).
- Los montos de `_purchase_sums` se **suman** al dict de `_projection_sums` antes de `_densify_projection`.
  Tasas, `event_date` y `minimum_payment` proyectado se calculan igual que hoy (sin cambios).
- Compras con `purchase_date ≤ closing_date` quedan **afuera**: se asumen capturadas por el resumen
  (Responsabilidad 1 / ítems). Al cargar el resumen siguiente, el filtro pasa al cierre nuevo y esas
  compras salen solas de la proyección.
- La moneda de la compra es holdable (Peso o Dólar en UY), así que cae en las series local/USD existentes.

---

## 3. Disparadores: re-materializar al escribir compras

`purchase_service` llama a `materialize_credit_card(db, card_id)` **antes del commit** (patrón de
`credit_card_service`) en toda escritura que involucre una tarjeta:

| Operación | Re-materializa |
|---|---|
| `create_purchase` con `credit_card_id` | esa tarjeta |
| `update_purchase` | la tarjeta final y, si el PATCH cambió de tarjeta o pasó a/desde efectivo, también la otra |
| `delete_purchase` de una compra con tarjeta | esa tarjeta |

Compras en efectivo (sin tarjeta en ningún momento) no disparan nada. El gate `is_ready` del engine aplica
igual (no-op silencioso). `materialize_credit_card` no commitea (flush); el commit único queda en el service.

---

## 4. Archivos

| Archivo | Cambio |
|---|---|
| `app/models/purchase.py` | columna `total_installments` |
| `alembic/versions/<rev>_add_total_installments_to_purchases.py` | `add_column` |
| `app/schemas/purchase.py` | campo en Create/Update/Out |
| `app/services/purchase_service.py` | validaciones de cuotas + disparadores de materialize |
| `app/services/cash_flow/credit_cards.py` | `_purchase_sums` + suma en Responsabilidad 2 |

---

## 5. Tests

Postgres `margin_test`. Fixtures existentes de `tests/test_purchases.py` (CRUD) y
`tests/test_cashflow_credit_cards.py` (engine: tarjeta + resumen + entries).

- **Validaciones** (`tests/test_purchases.py`): POST tarjeta + 6 cuotas ok (y sale en `PurchaseOut`);
  efectivo + 2 cuotas → `installments_invalid`; efectivo + 1 cuota ok; 0 cuotas → `installments_invalid`;
  PATCH a efectivo con cuotas previas → `installments_invalid`; ídem con `total_installments: null` en el
  mismo body → ok; PATCH `total_installments: null` vuelve a contado.
- **Engine** (`tests/test_cashflow_credit_cards.py`): compra post-cierre contado → suma en M+1;
  3 cuotas → M+1, M+2 y M+3; cuotas NULL = 1 cuota; compra con fecha ≤ cierre → excluida; compra de otra
  tarjeta → excluida; cuotas que pasan el horizonte → se cortan; compra en USD → serie USD; tarjeta sin
  resumen → las compras no proyectan (sin cambios de comportamiento).
- **Disparadores** (`tests/test_purchases.py` o el del engine): POST compra con tarjeta → las
  `cash_flow_entries` de la tarjeta reflejan la cuota en M+1; PATCH monto/cuotas → reproyecta; PATCH a
  efectivo → la compra sale de la proyección; DELETE → reproyecta; PATCH que cambia de tarjeta →
  re-materializa ambas.

---

## 6. Plan de implementación (orientativo)

Un slice (`feat/purchases-projection`), TDD: columna + migración → schemas → validaciones de cuotas →
`_purchase_sums` + integración en Responsabilidad 2 → disparadores en `purchase_service` → suite verde →
cierre (squash-merge).
