# CashFlowEngine.credit_cards (motor) — Diseño

> Sub-proyecto del subdominio **Tarjetas de crédito**. El motor que materializa `cash_flow_entries` a partir
> de los `credit_card_statements` promovidos de una tarjeta: materializa el último resumen y proyecta los
> meses siguientes (cuotas pendientes + suscripciones). **Solo el motor**, sin endpoints ni promote. Lo
> transversal de la familia vive en Notion → Backend → Engines → CashFlowEngine; lo propio en su subpágina
> `credit_cards`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tablas `credit_cards`, `credit_card_statements`, `credit_card_statement_items`,
  `cash_flow_entries`, `cash_flow_payments`, `currencies`, `countries` (todas en el repo). Reusa
  `app/services/cash_flow/rates.py` (`effective_rate`), `date_utils.py` (`compute_event_date`) y
  `scoping.legal_tender_currency`.
- **Cierre:** una rama por slice (`feat/cashflow-credit-cards-r1`, `feat/cashflow-credit-cards-r2`),
  **squash-merge** a `main` (1 commit/slice).

---

## 1. Alcance

Crear `app/services/cash_flow/credit_cards.py` con
`materialize_credit_card(db, credit_card_id, *, today=None, horizon=HORIZON)`, más tests. Espeja
`materialize_debt`: lock de la fuente, gate `is_ready`, target set reconciliado por **UPSERT manual** contra la
clave lógica, borrado acotado a futuras sin pago real, `db.flush()` sin commit.

**Fuera de alcance:** los endpoints (promote/acknowledge/PATCH que corren el reviewer y luego invocan al
motor), el promote en sí, el reviewer (ya hecho), el PlanEngine.

### Slices

| Slice | Rama | Contenido |
|---|---|---|
| **1** | `feat/cashflow-credit-cards-r1` | Gate + **Responsabilidad 1** (materializar el último resumen) + la reconciliación/borrado (target set = solo R1). Helper de moneda USD. |
| **2** | `feat/cashflow-credit-cards-r2` | **Responsabilidad 2** (proyección de meses siguientes), que **extiende** el target set; la reconciliación de R1 lo absorbe sin reescribirse. |

---

## 2. Contrato e invocación

Firma uniforme de la familia: `materialize_credit_card(db, credit_card_id, *, today=None, horizon=HORIZON)`.
`today=None → date.today()`; `HORIZON = date(2027, 12, 31)` (igual que los otros motores).

- Relee la tarjeta con `with_for_update`. None → `return`. `is_ready` false → **no-op silencioso** (no
  materializa, no error, no rollback).
- Corre sync en la transacción del endpoint. No hace commit.
- La invocan (sub-proyecto posterior) promote / acknowledge / PATCH, siempre con el `credit_card.id` tras
  correr el reviewer.

---

## 3. Mapeo de monedas

Los totales del resumen son **posicionales** (`total_local` / `total_usd`); el motor los mapea a `currency_id`:

- **local** = `scoping.legal_tender_currency(db, user)` (UY: Peso, id 1).
- **USD** = la moneda del país del usuario con `allowed_in_credit_card = true` **y** `is_legal_tender = false`
  (UY: Dólar, id 3). Helper nuevo `credit_card_usd_currency(db, user)` (en `scoping.py`, junto al de legal
  tender).

Las tasas de la tarjeta también son posicionales (`*_local` / `*_usd`): una entry en la moneda local usa las
tasas `_local`; una en USD, las `_usd`. Los ítems (R2) traen `currency_id` explícito; se clasifican comparando
contra el id local / USD.

> **Decisión:** identificar el USD por `allowed_in_credit_card AND NOT is_legal_tender` (no por código ISO, que
> `currencies` no tiene). Hoy en UY hay exactamente una moneda así. Si un país tuviera más de una, se
> replanteará; los totales del resumen sólo distinguen local/USD de todos modos.

---

## 4. Responsabilidad 1 — Materializar el último resumen

El "último resumen" = el `credit_card_statements` de la tarjeta con mayor `(issue_year, issue_month)` (mismo
criterio que el reviewer). Si la tarjeta no tiene resúmenes, R1 no aporta filas.

Genera hasta 2 filas objetivo (una por moneda con total > 0; total 0 o NULL → sin fila para esa moneda):

| campo | valor |
|---|---|
| `user_id` | dueño de la tarjeta |
| `is_income` | `false` |
| `amount` | `total_local` o `total_usd` (total del banco, no la suma de ítems) |
| `currency_id` | local o USD |
| `event_date` | `due_date` del resumen |
| `issue_year` / `issue_month` | **del `closing_date`** del resumen (`closing_date.year` / `.month`) |
| `minimum_payment` | `minimum_payment_local` o `minimum_payment_usd` |
| `financing_rate` / `overdue_rate` | efectivas, congeladas desde `credit_cards` para esa moneda (local→`_local`, USD→`_usd`), IVA resuelto con `rates_add_vat` + `countries.vat_rate`. NULL si la tarjeta no las tiene |
| `source_type` | `'tarjeta_credito'` |
| `source_id` | **id de la tarjeta** (no del resumen) |

---

## 5. Responsabilidad 2 — Proyección de meses siguientes

A partir de los `credit_card_statement_items` del último resumen, proyecta de `M+1` al horizonte, donde `M` es
el mes del resumen (`closing_date.year`/`.month`, mismo ancla que R1).

Por cada ítem:
- **En cuotas** (`current_installment` y `total_installments` con valor): faltan
  `total_installments − current_installment` cuotas → una por mes consecutivo desde `M+1`. Cada una aporta
  `item.amount` a su mes/moneda.
- **Suscripción** (`item_type_id` cuyo `code = 'suscripcion'`): aporta `item.amount` **todos los meses** de
  `M+1` al horizonte.
- **Compra de un pago** (sin cuotas y no suscripción): no se proyecta.

Las proyecciones se **agrupan por (mes, moneda)** sumando los aportes. Cada fila:

| campo | valor |
|---|---|
| `event_date` | `compute_event_date(year, month, card.closing_day, shift_weekends=False)` (clamp a fin de mes, sin corrimiento de finde) |
| `issue_year` / `issue_month` | el mes proyectado |
| `amount` | suma de cuotas/suscripciones de esa moneda en ese mes |
| `minimum_payment` | `NULL` |
| `financing_rate` / `overdue_rate` | efectivas desde las tasas vigentes de la tarjeta, por moneda (igual que R1) |
| `is_income` / `source_type` / `source_id` | `false` / `'tarjeta_credito'` / id de la tarjeta |

> El `item_type_id` de `suscripcion` se resuelve una vez por corrida (lookup en `credit_card_item_types` por
> `code`).

---

## 6. Reconciliación (común a R1 + R2)

El target set de una corrida = filas de R1 (mes del resumen) ∪ filas de R2 (M+1..horizonte). Se reconcilia
contra **todas** las `cash_flow_entries` `tarjeta_credito` de la tarjeta por la **clave lógica**:

```
(source_type='tarjeta_credito', source_id=card.id, issue_year, issue_month, currency_id)
```

- Por cada target: buscar la entry por la clave; **UPDATE** si existe, **INSERT** si no.
- Entries existentes fuera del target: **borrar solo si** `event_date >= today` (futuras) **y** sin pago real
  (`cash_flow_payments` con `plan_id IS NULL`). Con pago real → `RuntimeError` (rollback). Las **pasadas** no
  se tocan.

Esto da la convivencia proyección↔real: cuando llega el resumen real de un mes antes proyectado, R1 lo
materializa por la misma clave y **pisa** la proyección (no duplica); los resúmenes viejos (pasado) quedan
intactos; las proyecciones futuras que dejaron de corresponder (p.ej. una cuota que se terminó) se borran.

---

## 7. Decisiones, con su porqué

- **Clave lógica por columnas `issue_year`/`issue_month`** (no por `event_date.year/month` como en `debts`):
  en tarjetas el período de emisión y el vencimiento son independientes; la clave debe ser el período, que
  vive en columnas propias. Por eso `cash_flow_entries` ya las tiene.
- **`source_id` = la tarjeta, no el resumen:** así R2 cuelga proyecciones de la misma tarjeta y R1 las
  reconcilia por clave. Una sola fuente para toda la tarjeta.
- **Borrado acotado a futuras sin pago real (regla transversal):** el pasado no se reescribe; los resúmenes
  promovidos viejos perduran. Igual que `materialize_debt`.
- **USD por `allowed_in_credit_card AND NOT is_legal_tender`** (§3).
- **`today`/`horizon` inyectables:** tests deterministas, igual que los otros motores.
- **Proyección sin corrimiento de finde:** el `closing_day` se clampea al mes pero no se corre por fin de
  semana (Notion solo menciona el clamp para tarjetas).
- **Suscripción por `code`, no por id hardcodeado:** robusto ante reordenamientos del seed.
- **Layering R1→R2:** R1 escribe la reconciliación sobre "el target set"; R2 sólo agranda ese set. El código
  de borrado/UPSERT no cambia entre slices.

---

## 8. Tests

Reusar `seed_cc_refs` (conftest, da user + institución/red/tipo + Peso id 1). Sembrar además la moneda **USD**
(Dólar id 3, `allowed_in_credit_card=True`, `is_legal_tender=False`) y, donde haga falta, el tipo
`suscripcion` (id 3) en `credit_card_item_types`. Helpers para crear tarjeta lista (`is_ready=True`),
resumen e ítems. `today`/`horizon` fijos.

### Slice 1 (`tests/test_cashflow_credit_cards.py`)

- **Gate:** tarjeta `is_ready=False` → no escribe ninguna entry; tarjeta inexistente → no-op.
- **Dos monedas:** resumen con `total_local>0` y `total_usd>0` → 2 entries con `amount`, `currency_id`,
  `event_date=due_date`, `issue` del `closing_date`, `minimum_payment` por moneda, tasas efectivas por moneda
  (local→`_local`, USD→`_usd`, con IVA), `source_id`=tarjeta.
- **Total 0/NULL:** `total_usd=0` → solo la fila local.
- **Tasas NULL:** tarjeta con una tasa en NULL → la entry lleva esa tasa NULL.
- **Reconciliación UPDATE:** correr dos veces (segundo resumen del mismo período con otro `amount`) → actualiza
  la fila, no duplica.
- **Borrado de moneda que perdió total:** primero `total_usd>0` (crea fila USD futura), luego `total_usd=0` →
  la fila USD futura se borra; la local queda.
- **No borra con pago real:** una entry futura con `cash_flow_payments` (`plan_id IS NULL`) que quedaría fuera
  del target → `RuntimeError`.
- **No toca el pasado:** una entry pasada fuera del target no se borra.
- **Tasas efectivas:** verificar el cálculo con `vat_rate` del país (p.ej. 22 → ×1.22, ROUND_HALF_UP).

### Slice 2 (extiende el mismo test file)

- **Cuota pendiente:** ítem `3/4` (Peso) en el resumen de mayo → 1 proyección en junio (mes M+1), `amount` =
  el de la cuota, `issue` de junio, `event_date` = `closing_day` de junio, `minimum_payment` NULL.
- **Suscripción:** ítem suscripción (USD) → proyección **todos los meses** de M+1 al horizonte.
- **Compra de un pago:** ítem sin cuotas y no suscripción → no proyecta.
- **Agrupación por moneda/mes:** dos ítems de la misma moneda que caen en el mismo mes → una sola fila con la
  suma.
- **Clamp de `closing_day`:** `closing_day=31` proyectado en un mes de 30 → `event_date` = último día del mes.
- **Convivencia con real:** proyectar (resumen abril) y luego promover el resumen real de mayo → la fila de
  mayo pasa de proyección a real (mismo `(issue, moneda)`, `event_date`→`due_date`, `amount`→total,
  `minimum_payment`→del resumen), sin duplicar.
- **Reproyección al achicarse:** al avanzar el cronograma (menos cuotas pendientes) las proyecciones futuras
  sobrantes se borran.

---

## 9. Plan de implementación (orientativo)

Dos slices, cada uno TDD + squash-merge:
1. **`feat/cashflow-credit-cards-r1`** — helper USD en `scoping.py`; `materialize_credit_card` con gate + R1 +
   reconciliación/borrado; tests de slice 1.
2. **`feat/cashflow-credit-cards-r2`** — extender el motor con la proyección (R2) y el target set; tests de
   slice 2.
