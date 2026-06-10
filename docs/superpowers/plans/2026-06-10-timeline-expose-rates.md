# timeline — exponer financing_rate / overdue_rate / minimum_payment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans o
> superpowers:subagent-driven-development. Steps con checkbox (`- [ ]`).

**Goal:** El `GET /cash-flow-entries` expone por row `financing_rate`, `overdue_rate` y `minimum_payment` (ya en
la tabla; falta traerlas en el SQL y serializarlas).

**Architecture:** Cambio de **lectura** en `cash_flow_entry_service.py` (`_TIMELINE_SQL` + `_entry_fields`) y el
schema `TimelineEntryOut`. Sin tabla nueva, sin migración, sin web. No cambia montos ni totales.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-timeline-expose-rates-design.md`

**Branch:** `feat/timeline-expose-rates`. Squash-merge al final. **No Notion. Sin web.**

**Higiene:** `cd .../backend && source .venv/bin/activate && pytest -q` (sin pipes/`2>&1`). Git planos. No push.

**Estado actual (verificado):**
- `_TIMELINE_SQL` ([cash_flow_entry_service.py:18](../../../backend/app/services/cash_flow_entry_service.py#L18)):
  CTE `entries` (4 ramas: obligations / incomes / plan_movements / credit_cards), `entries_with_payments`,
  `open_debt_monthly`, `unified` (UNION ALL **posicional**), SELECT final con `*_converted`. Usa
  `:user_id`/`:plan_id`.
- `_entry_fields` arma el dict de campos por row (sin los 3 nuevos).
- `TimelineEntryOut` (lo hereda `MonthEntryOut`) tiene `…_converted`; sin los 3 nuevos.
- Tests: helpers `_headers`, `_last_user`, `_plan`, `_card`, `_card_entry`, `_income_entry`, `_pay`,
  `_open_debt`, `_entry`; `svc = cash_flow_entry_service`; `CashFlowEntry`/`Decimal`/`date` importados.
- `_card` crea CreditCard (institution_id=1, card_network_id=1 de `seed_cc_refs`). `_income_entry` crea
  `plan_movimiento_entrada` (rama plan_movements → `minimum_payment = cfe.amount`).

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/timeline-expose-rates
```

---

## Task 1: Exponer los 3 campos (TDD)

**Files:** `app/services/cash_flow_entry_service.py`, `app/schemas/cash_flow_entry.py`,
`tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Tests nuevos (rojo)** — agregar a `tests/test_get_cash_flow_entries.py`:

```python
def test_timeline_exposes_card_rates(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user)
    db_session.add(CashFlowEntry(
        user_id=user.id, event_date=date(2026, 6, 10), is_income=False, amount=Decimal("6000.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("84.18"), overdue_rate=Decimal("97.60"), minimum_payment=Decimal("1006.00"),
    ))
    db_session.commit()
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert Decimal(e["financing_rate"]) == Decimal("84.18")
    assert Decimal(e["overdue_rate"]) == Decimal("97.60")
    assert Decimal(e["minimum_payment"]) == Decimal("1006.00")


def test_timeline_card_null_minimum_and_zero_rates(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="1500.00")  # sin rates ni minimum
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert Decimal(e["financing_rate"]) == Decimal("0")   # COALESCE(.,0)
    assert Decimal(e["overdue_rate"]) == Decimal("0")
    assert e["minimum_payment"] is None                   # tarjeta: cfe.minimum_payment (null)


def test_timeline_plan_movement_minimum_is_amount(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 5), amount="45000.00")
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["incomes"][0]
    assert Decimal(e["financing_rate"]) == Decimal("0")
    assert Decimal(e["overdue_rate"]) == Decimal("0")
    assert Decimal(e["minimum_payment"]) == Decimal("45000.00")  # plan_movements: cfe.amount
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_timeline_exposes_card_rates -q
```

Expected: FALLA (`KeyError`/campo inexistente — el SQL/schema aún no traen los 3 campos).

- [ ] **Step 3: `_TIMELINE_SQL`** — reemplazar el bloque `text("""…""")` por (3 campos en las 4 ramas,
  propagados en `entries_with_payments` y `open_debt_monthly` —orden correcto— y en el SELECT final):

```python
_TIMELINE_SQL = text(
    """
WITH entries AS (
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, o.description,
         COALESCE(cfe.financing_rate, 0) AS financing_rate,
         COALESCE(cfe.overdue_rate, 0)   AS overdue_rate,
         cfe.amount                      AS minimum_payment
  FROM cash_flow_entries cfe
  JOIN obligations o ON o.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type IN ('gasto', 'deuda', 'deuda_abierta')
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, i.description,
         0 AS financing_rate, 0 AS overdue_rate, 0 AS minimum_payment
  FROM cash_flow_entries cfe
  JOIN incomes i ON i.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type = 'ingreso'
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, pm.description,
         COALESCE(cfe.financing_rate, 0) AS financing_rate,
         COALESCE(cfe.overdue_rate, 0)   AS overdue_rate,
         cfe.amount                      AS minimum_payment
  FROM cash_flow_entries cfe
  JOIN plan_movements pm ON pm.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type IN ('plan_movimiento', 'plan_movimiento_entrada')
    AND pm.plan_id = :plan_id
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income,
         inst.name || ' ' || ccn.name AS description,
         COALESCE(cfe.financing_rate, 0) AS financing_rate,
         COALESCE(cfe.overdue_rate, 0)   AS overdue_rate,
         cfe.minimum_payment             AS minimum_payment
  FROM cash_flow_entries cfe
  JOIN credit_cards cc          ON cc.id = cfe.source_id
  JOIN institutions inst        ON inst.id = cc.institution_id
  JOIN credit_card_networks ccn ON ccn.id = cc.card_network_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type = 'tarjeta_credito'
),
entries_with_payments AS (
  SELECT
    e.id, e.event_date, e.amount, e.currency_id,
    e.source_type, e.source_id, e.is_income, e.description,
    e.financing_rate, e.overdue_rate, e.minimum_payment,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id IS NULL), 0.00)    AS paid_real,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0.00) AS planned_amount
  FROM entries e
  LEFT JOIN cash_flow_payments p ON p.cash_flow_entry_id = e.id
  GROUP BY e.id, e.event_date, e.amount, e.currency_id,
           e.source_type, e.source_id, e.is_income, e.description,
           e.financing_rate, e.overdue_rate, e.minimum_payment
),
open_debt_monthly AS (
  SELECT
    cfe.id,
    MIN(COALESCE(p.planned_date, p.created_at::date))              AS event_date,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0.00) AS amount,
    cfe.currency_id,
    cfe.source_type,
    cfe.source_id,
    cfe.is_income,
    o.description,
    0 AS financing_rate, 0 AS overdue_rate, 0 AS minimum_payment,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id IS NULL), 0.00)    AS paid_real,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0.00) AS planned_amount
  FROM cash_flow_payments p
  JOIN cash_flow_entries cfe ON cfe.id = p.cash_flow_entry_id
  JOIN obligations o ON o.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type = 'deuda_abierta'
    AND (p.plan_id IS NULL OR p.plan_id = :plan_id)
  GROUP BY cfe.id, cfe.currency_id, cfe.source_type, cfe.source_id,
           cfe.is_income, o.description,
           date_trunc('month', COALESCE(p.planned_date, p.created_at::date))
),
unified AS (
  SELECT * FROM entries_with_payments
  UNION ALL
  SELECT * FROM open_debt_monthly
)
SELECT
  u.id, u.event_date, u.amount, u.currency_id,
  u.source_type, u.source_id, u.is_income, u.description,
  u.paid_real, u.planned_amount,
  u.amount         * COALESCE(cr.value, 1) AS amount_converted,
  u.paid_real      * COALESCE(cr.value, 1) AS paid_real_converted,
  u.planned_amount * COALESCE(cr.value, 1) AS planned_amount_converted,
  u.financing_rate, u.overdue_rate, u.minimum_payment
FROM unified u
LEFT JOIN currency_rates cr
  ON cr.currency_id = u.currency_id
  AND cr.rate_date  = COALESCE(u.event_date, CURRENT_DATE)
ORDER BY u.event_date ASC NULLS LAST
"""
)
```

- [ ] **Step 4: `_entry_fields`** — sumar las 3 lecturas (después de `planned_amount_converted=…`):

```python
        planned_amount_converted=r["planned_amount_converted"],
        financing_rate=r["financing_rate"],
        overdue_rate=r["overdue_rate"],
        minimum_payment=r["minimum_payment"],
```

- [ ] **Step 5: Schema** — en `app/schemas/cash_flow_entry.py`, `TimelineEntryOut`, después de
  `planned_amount_converted: Decimal`:

```python
    financing_rate: Decimal
    overdue_rate: Decimal
    minimum_payment: Decimal | None
```

- [ ] **Step 6: Run los 3 tests nuevos → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_timeline_exposes_card_rates tests/test_get_cash_flow_entries.py::test_timeline_card_null_minimum_and_zero_rates tests/test_get_cash_flow_entries.py::test_timeline_plan_movement_minimum_is_amount -q
```

Expected: PASS.

- [ ] **Step 7: Guarda del Bug 2 — plegar en `test_open_debt_projected_into_month`.** Agregar un pago real en
  julio y 2 asserts; actualizar el `pending_expenses` de julio (ahora neto del pago real).

Tras la línea `_pay(db_session, entry, amount="5000.00", plan_id=plan.id, planned_date=date(2026, 7, 15))`
agregar:

```python
    _pay(db_session, entry, amount="1000.00", planned_date=date(2026, 7, 20))  # pago real en julio (guarda Bug 2)
```

Tras `assert proj["amount"] == "5000.00"` agregar:

```python
    assert Decimal(proj["paid_real"]) == Decimal("1000.00")   # no intercambiado con financing_rate
    assert Decimal(proj["financing_rate"]) == Decimal("0")    # open_debt: literal 0 (orden correcto del UNION)
```

Y cambiar el assert final del `pending_expenses` de julio:

```python
    assert jul_obj.pending_expenses == Decimal("4000.00")  # 5000 planificado − 1000 real
```

- [ ] **Step 8: Run el archivo completo → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q
```

Expected: PASS (cambio aditivo; el resto del timeline no se toca).

- [ ] **Step 9: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_entry_service.py app/schemas/cash_flow_entry.py tests/test_get_cash_flow_entries.py && git commit -m "feat: timeline expone financing_rate, overdue_rate y minimum_payment por row"
```

---

## Task 2: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde.

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: superpowers:finishing-a-development-branch. **squash-merge** a
  `main` (1 commit). Push **manual**. Sin Notion.

---

## Self-Review

- **Cobertura del spec:** §2 SQL (3 campos en 4 ramas + propagación + fix de orden en open_debt) — Task 1
  Step 3; §3 `_entry_fields` — Step 4; §4 schema — Step 5; §7 tests (tarjeta con/ sin minimum, plan_movement
  minimum=amount, guarda open_debt plegada) — Steps 1 y 7. ✓
- **Placeholder scan:** sin TBD/TODO; SQL completo; código de tests completo. ✓
- **Consistencia:** `financing_rate`/`overdue_rate` no-null (COALESCE) → `Decimal`; `minimum_payment` nullable →
  `Decimal | None`. Orden de los 3 campos idéntico en `entries_with_payments` y `open_debt_monthly` (antes de
  paid_real/planned_amount) ⇒ `unified` (UNION ALL posicional) alineado. `_entry_fields` cubre rows de mes y
  `open_debts`. ✓
- **Aditivo:** no cambia montos ni totales; tests existentes siguen verdes salvo el `pending_expenses` de julio
  (ajustado por el pago real que suma la guarda). ✓
