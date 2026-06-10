# timeline — `available` ancla en el mes actual — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans o
> superpowers:subagent-driven-development. Steps con checkbox (`- [ ]`).

**Goal:** El `available` (efectivo) y el arrastre del `balance` se anclan en el **mes calendario actual**, no en
`months[0]`. Los meses pasados quedan con los 5 totales en 0 y no arrastran.

**Architecture:** Solo el armado de `months[]` en `get_timeline` (`cash_flow_entry_service.py`). Sin schema,
sin migración, sin web.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-timeline-available-anchor-design.md`

**Branch:** `feat/timeline-available-anchor`. Squash-merge al final. **No Notion. Sin web.**

**Higiene:** `cd .../backend && source .venv/bin/activate && pytest -q` (sin pipes/`2>&1`). Git planos. No push.

**Estado actual (verificado):** `get_timeline` arma `months[]` con `for i, key in enumerate(sorted(buckets))`,
tratando `i == 0` como ancla (`available = _available_now`, `remaining_spending = dial_prorated`) y arrastrando
`prev_balance`. `today` ya es parámetro (default `date.today()`). Helpers de test: `_headers`, `_last_user`,
`_plan`, `_plan_dial`, `_cash`, `_card_entry`, `_income_entry`, `_pay`; `svc = cash_flow_entry_service`.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/timeline-available-anchor
```

---

## Task 1: Ancla en el mes actual (TDD)

**Files:** `app/services/cash_flow_entry_service.py`, `tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Test nuevo (rojo)** — agregar a `tests/test_get_cash_flow_entries.py`:

```python
def test_past_month_zeroed_and_not_carried(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan_dial(db_session, user, "0")
    _cash(db_session, user, 1, "10000.00")
    _card_entry(db_session, user, event_date=date(2026, 5, 10), amount="3000.00")            # mes pasado
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 10), amount="5000.00")    # mes actual
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    may, jun = out.months[0], out.months[1]
    assert may.month == "2026-05"
    assert may.available == Decimal("0")
    assert may.pending_income == Decimal("0")
    assert may.pending_expenses == Decimal("0")
    assert may.remaining_spending == Decimal("0")
    assert may.balance == Decimal("0")
    assert len(may.expenses) == 1                 # la row del mes pasado igual aparece
    assert jun.available == Decimal("10000.00")   # el mes actual arranca con el efectivo, sin arrastrar mayo
    assert jun.balance == Decimal("15000.00")     # (10000 + 5000) − (0 + 0)
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest "tests/test_get_cash_flow_entries.py::test_past_month_zeroed_and_not_carried" -q
```

Expected: FALLA (hoy mayo se ancla con el efectivo y arrastra).

- [ ] **Step 3: Cambiar el armado de meses en `get_timeline`.** Reemplazar el bloque
  `months: list[MonthOut] = [] ... return TimelineOut(...)` por:

```python
    current_key = today.strftime("%Y-%m")
    months: list[MonthOut] = []
    prev_balance: Decimal | None = None
    for key in sorted(buckets):
        b = buckets[key]
        b["incomes"].sort(key=lambda e: (e.event_date, str(e.id)))
        b["expenses"].sort(key=lambda e: (e.event_date, str(e.id)))
        if key < current_key:
            # mes pasado: histórico, totales en 0, no arrastra
            available = pending_income = pending_expenses = remaining_spending = balance = Decimal("0")
        else:
            if prev_balance is None:  # primer mes >= actual = ancla del efectivo
                available = _available_now(db, user, today)
                remaining_spending = dial_prorated if key == current_key else dial
            else:
                available = prev_balance
                remaining_spending = dial
            pending_income = b["pi"]
            pending_expenses = b["pe"]
            balance = (available + pending_income) - (pending_expenses + remaining_spending)
            prev_balance = balance
        months.append(
            MonthOut(
                month=key,
                available=available,
                pending_income=pending_income,
                pending_expenses=pending_expenses,
                remaining_spending=remaining_spending,
                balance=balance,
                incomes=b["incomes"],
                expenses=b["expenses"],
            )
        )

    return TimelineOut(months=months, open_debts=open_debts)
```

- [ ] **Step 4: Run el test nuevo → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest "tests/test_get_cash_flow_entries.py::test_past_month_zeroed_and_not_carried" -q
```

- [ ] **Step 5: Determinismo — fijar `today` en los tests de totales.** Tres tests asertan totales del mes y
  hoy dependen de `date.today()`; con el zerado de pasados se vuelven sensibles a la fecha de corrida.

(a) `test_pending_nets_paid_real`: agregar `today` a la llamada existente:

```python
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
```

(b) `test_timeline_groups_by_month_and_flow`: **reemplazar** los 3 asserts de agregados del JSON
(`jun["pending_income"]`, `jun["pending_expenses"]`, `jun["balance"]`) por una verificación vía `svc` con
`today` fijo (dejar el resto del test —estructura, `is_income` no serializado, `open_debts == []`— tal cual,
que no depende de la fecha):

```python
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 5))
    jun_obj = out.months[0]
    assert jun_obj.pending_income == Decimal("45000.00")
    assert jun_obj.pending_expenses == Decimal("6000.00")
    assert jun_obj.balance == Decimal("39000.00")
```

(c) `test_open_debt_projected_into_month`: **reemplazar** el assert final `assert jul["pending_expenses"] == "5000.00"`
por la verificación vía `svc` con `today` fijo (junio actual, julio futuro):

```python
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jul_obj = next(m for m in out.months if m.month == "2026-07")
    assert jul_obj.pending_expenses == Decimal("5000.00")
```

- [ ] **Step 6: Run el archivo completo → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_entry_service.py tests/test_get_cash_flow_entries.py && git commit -m "feat: el available del timeline se ancla en el mes actual; pasados en 0"
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

- **Cobertura del spec:** ancla = mes actual (`current_key`); pasados con los 5 totales en 0 y sin arrastre;
  ancla = primer mes ≥ actual (prorrateo solo si es el mes actual); rows de pasados visibles (`len(may.expenses)`).
  Tests de totales pasan a inyectar `today` (determinismo). ✓
- **Placeholder scan:** sin TBD/TODO ni código roto. ✓
- **Consistencia:** `current_key` se compara con `key` (`"YYYY-MM"`, lexicográfico); `prev_balance is None`
  marca el ancla; `pending_income`/`pending_expenses` se fuerzan a 0 en pasados (no se usa `b["pi"]/b["pe"]`).
  `today` ya está resuelto arriba en `get_timeline`. ✓
- **Riesgo:** otros tests del archivo que asertan agregados del mes vía endpoint romperían si su mes cae en el
  pasado al correr; los 3 identificados se fijan con `today`. Si la suite marca otro, aplicar el mismo patrón. ✓
