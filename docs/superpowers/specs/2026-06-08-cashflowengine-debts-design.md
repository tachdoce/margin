# CashFlowEngine.debts (motor) — Diseño

> Sub-proyecto #3 del subdominio **Obligaciones**. Materializa `cash_flow_entries` desde las `obligations`
> con `obligation_kind = 'deuda'`. **Solo el motor**, sin endpoints. Comparte toda la estructura del motor
> `expenses` (#2, en `main`); agrega el cronograma de cuotas y las tasas efectivas congeladas. El *qué* está
> en Notion → Backend → Engines → CashFlowEngine → `debts`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tabla `obligations`, `cash_flow_entries`/`cash_flow_payments`, `compute_event_date`,
  `countries.vat_rate` (todo en `main`).
- **Cierre:** rama `feat/cashflow-debts`, **squash-merge** a `main`.

---

## 1. Alcance

Crear `app/services/cash_flow/debts.py` con `materialize_debt(db, obligation_id, *, today=None,
horizon=HORIZON)`, más tests. No hace commit (lo controla el caller).

**Fuera de alcance:** endpoints, ReviewEngine, motores `open_debts`. La extracción de un reconciliador
compartido y de `_effective_rate` queda **diferida** (se replican por ahora, decisión del brainstorming).

---

## 2. Comparte con `expenses` (plantilla)

Espeja `materialize_expense` ([expenses.py](../../../backend/app/services/cash_flow/expenses.py)):
`HORIZON`, `_iter_months`, gate `is_ready` (no-op si false), `SELECT ... FOR UPDATE` sobre la obligación,
UPSERT contra clave lógica, borrado de stale **solo futuras sin pago real** (raise si una futura stale tiene
pago real), pasado intacto, `flush` sin commit. `source_type = 'deuda'`, `is_income = False`. `is_closed` →
objetivo vacío. Se copian esos patrones y se agregan los puntos de §3–§4.

---

## 3. Cálculo del objetivo (las dos formas)

`_target_event_dates(obligation, today, horizon)`:
- Si `is_closed` → `[]`.
- **Cronograma** (`total_installments` no NULL): si `due_day` es NULL → **raise** (estado imposible; sin
  fallback al día de `first_due_date`). Para `N` en `0..total_installments-1`, mes nominal = mes de
  `first_due_date` + N; `ed = compute_event_date(año, mes, due_day, shift_weekends)`; incluir si
  `today <= ed <= horizon`. (El conjunto resultante es contiguo porque `ed` crece con N.)
- **Pago único** (`total_installments` NULL, `first_due_date` con valor): un solo `ed = compute_event_date(
  first_due_date.año, .mes, .día, shift_weekends)`; incluir si `today <= ed <= horizon`.

El monto de cada fila es `obligations.amount` tal cual — **el motor no calcula amortización**.

## 4. Tasas efectivas congeladas

Cada fila guarda la **tasa efectiva** (IVA ya resuelto), no la cruda. Se replica el helper de
`plan_movements` ([plan_movements.py:32-37](../../../backend/app/services/cash_flow/plan_movements.py#L32-L37)):

```python
def _effective_rate(rate: Decimal | None, rates_add_vat: bool, vat_rate: Decimal) -> Decimal | None:
    if rate is None:
        return None
    if rates_add_vat:
        rate = rate * (Decimal(1) + vat_rate / Decimal(100))
    return rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

- `vat_rate` = `db.get(Country, user.country_code).vat_rate`, con `user = db.get(User, obligation.user_id)`.
- Se computan `fin_eff` y `over_eff` **una vez** por obligación (antes del loop): son iguales para todas las
  filas.
- En cada INSERT y en cada UPDATE de entry futura, se escriben `financing_rate = fin_eff` y
  `overdue_rate = over_eff`. Tasa NULL en la fuente → NULL en la entry. Las pasadas no se tocan (foto
  histórica). Son **informativas** (no se aplican al `amount`).

## 5. Clave lógica y reconciliación

Idéntica a `expenses` salvo el `source_type`:
- **Clave:** `(source_type='deuda', source_id, año(event_date), mes(event_date), currency_id)`.
- **UPSERT:** por cada `ed` objetivo, buscar por `(año, mes, currency_id)`; si está → UPDATE (`amount`,
  `event_date`, `financing_rate`, `overdue_rate`); si no → INSERT (con tasas efectivas).
- **Stale:** existentes fuera del objetivo → borrar solo futuras (`event_date >= today`) sin pago real;
  futura stale con pago real → **raise** (rollback). Pasadas y planificados como en `expenses`.

## 6. Decisiones, con su porqué

- **Sin amortización:** el `amount` cargado por el usuario es el valor de cada cuota; las tasas son
  informativas (Notion). El motor no deriva cuotas de capital+tasa.
- **Tasa efectiva congelada (no cruda + flag):** la entry es la foto del costo real del mes; congelar la
  efectiva evita recomputar y mantiene fiel el histórico aunque la fuente cambie después.
- **`_effective_rate` replicado, no extraído (todavía):** consistente con la decisión de espejar los motores;
  se extrae junto con la reconciliación cuando consolidemos (post `open_debts`).
- **Sin fallback de `due_day` en cronograma:** estado imposible en modelo consistente; el motor lanza
  excepción en vez de inventar fecha.
- **Gate dentro del motor, `today`/`horizon` inyectables:** igual que el resto de la familia.

## 7. Tests (`tests/test_cashflow_debts.py`)

Sembrando UY (vat_rate 22.00) + currency + priority_levels + obligation_type de deuda + usuario + una
`obligations` de deuda (helper). `today`/`horizon` fijos.

- **Cronograma:** materializa las cuotas con `today <= venc <= horizon`; cada una `is_income=False`,
  `source_type='deuda'`, `amount = obligations.amount`, fecha por `due_day`.
- **Tasas efectivas:** `rates_add_vat=true` → `financing_rate` congelada = cruda ×1.22 (ej. 55 → 67.10);
  `rates_add_vat=false` → = cruda (55.00); tasa NULL → NULL en la entry.
- **Pago único:** `total_installments` NULL, `first_due_date` con valor → 1 fila en esa fecha.
- **Gate `is_ready=false`:** no materializa; deja existentes intactas.
- **`is_closed=true`:** borra futuras sin pago real.
- **Acortar cronograma** (menos `total_installments`): borra las cuotas que sobran (futuras, sin pago) por
  UPSERT.
- **Cambio de tasas:** reescribe `financing_rate`/`overdue_rate` de las futuras; las pasadas quedan con la
  efectiva vieja.
- **Pago real stale → raise**; **pago planificado stale → se borra**.
- **Pasado intacto.**
- **`due_day` NULL en cronograma → raise.**
- **shift_weekends:** una cuota cuyo `due_day` cae finde se corre (1 caso de humo).

## 8. Plan de implementación (orientativo)

Un slice (`feat/cashflow-debts`), TDD:
1. `tests/test_cashflow_debts.py` (rojo) → `app/services/cash_flow/debts.py` (verde) → commit.
2. Suite completa verde → cierre.
