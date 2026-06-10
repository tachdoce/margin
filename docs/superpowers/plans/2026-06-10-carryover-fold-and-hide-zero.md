# timeline — plegar el arrastre en el loop + ocultar rows en 0 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans o
> superpowers:subagent-driven-development. Steps con checkbox (`- [ ]`).

**Goal:** Plegar el arrastre de tarjeta dentro del loop de `get_timeline` (en vez del post-paso
`_apply_card_carryover`) y ocultar de la respuesta las rows con `amount == 0`.

**Architecture:** El `carry` se suma al `amount`/`amount_converted` **antes** de derivar efectivo/pendiente;
`_effective_planned` (refactorizado a args explícitos) da `planned = amount` (sin plan) o la parte planificada;
`minimum_payment` se recomputa al 15%. Se elimina `_apply_card_carryover` y el ajuste manual de `pe`. Al final,
filtro de `amount == 0` en rows de meses y `open_debts` (presentación; totales y persistencia intactos).

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Decimal · pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-carryover-fold-and-hide-zero-design.md`

**Branch:** `feat/carryover-fold-and-hide-zero`. Squash-merge al final. **No Notion. Sin web.**

**Higiene:** `cd .../backend && source .venv/bin/activate && pytest -q` (sin pipes/`2>&1`). Git planos. No push.

**Estado actual (verificado):** `_effective_planned(r)` toma `r`. `_apply_card_carryover(db, buckets, today,
current_key)` es un post-paso que sube amount/min y `pe`. El row loop usa `_effective_planned(r)`; `current_key`
se calcula **después** del loop; el loop de meses arma `MonthOut(... incomes=b["incomes"],
expenses=b["expenses"])` y `return TimelineOut(months=months, open_debts=open_debts)`. `monthly_carry`,
`PROJECTED_MINIMUM_RATE`, `_rate`, `ROUND_HALF_UP`, `Decimal` ya importados.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/carryover-fold-and-hide-zero
```

---

## Task 1: Plegar el arrastre + ocultar 0 (TDD)

**Files:** `app/services/cash_flow_entry_service.py`, `tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Tests** — en `tests/test_get_cash_flow_entries.py`:

(a) En `test_carryover_adds_prev_unpaid_to_current_month`, tras `assert row.amount == Decimal("810.80")`,
agregar:

```python
    assert row.planned_amount == Decimal("810.80")             # sin plan -> planned = amount (deuda entera)
    assert row.planned_amount_converted == row.amount_converted
```

(b) **Reemplazar** el cuerpo de `test_carryover_skips_when_prev_settled` desde
`out = svc.get_timeline(...)` hasta el final por:

```python
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = next(m for m in out.months if m.month == "2026-06")
    assert jun.expenses == []  # mes anterior saldado -> row en 0 oculta; el mes sigue (sin rows)
```

(c) **Agregar** dos tests nuevos:

```python
def test_carryover_partial_plan_keeps_planned(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user)
    prev = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 5, 29), is_income=False, amount=Decimal("1000.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("100.00"),
    )
    db_session.add(prev)
    db_session.commit()
    db_session.refresh(prev)
    _pay(db_session, prev, amount="200.00")  # mayo: pagó el mínimo -> financiación; saldo 800 -> carry 810.80
    jun_entry = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 6, 29), is_income=False, amount=Decimal("0.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("0.00"),
    )
    db_session.add(jun_entry)
    db_session.commit()
    db_session.refresh(jun_entry)
    _pay(db_session, jun_entry, amount="300.00", plan_id=plan.id, planned_date=date(2026, 6, 29))  # planifica pagar 300
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = next(m for m in out.months if m.month == "2026-06")
    row = next(e for e in jun.expenses if str(e.source_id) == str(card.id))
    assert row.amount == Decimal("810.80")             # deuda arrastrada (saldo 800 + interés 10.80)
    assert row.planned_amount == Decimal("300.00")     # planifica pagar solo una parte
    assert jun.pending_expenses == Decimal("300.00")   # no se cuenta doble: pendiente = lo planificado


def test_zero_amount_rows_hidden(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user)
    # una row de relleno en el mes actual, sin arrastre ni plan -> amount 0 -> oculta
    db_session.add(CashFlowEntry(
        user_id=user.id, event_date=date(2026, 6, 29), is_income=False, amount=Decimal("0.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("0.00"),
    ))
    db_session.commit()
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = next((m for m in out.months if m.month == "2026-06"), None)
    assert jun is not None and jun.expenses == []  # el mes se muestra, sin la row en 0
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_carryover_adds_prev_unpaid_to_current_month tests/test_get_cash_flow_entries.py::test_carryover_skips_when_prev_settled tests/test_get_cash_flow_entries.py::test_carryover_partial_plan_keeps_planned tests/test_get_cash_flow_entries.py::test_zero_amount_rows_hidden -q
```

Expected: fallan (planned no = amount; rows en 0 todavía visibles; plan parcial no respetado).

- [ ] **Step 3: `_effective_planned` con args explícitos** — reemplazar la función:

```python
def _effective_planned(planned_amount, planned_amount_converted, amount, amount_converted):
    """Monto efectivo: el planificado si lo hay, si no el proyectado (amount)."""
    if planned_amount > 0:
        return planned_amount, planned_amount_converted
    return amount, amount_converted
```

- [ ] **Step 4: Eliminar `_apply_card_carryover`** — borrar toda la función `_apply_card_carryover(...)`
  (def + cuerpo).

- [ ] **Step 5: Plegar el arrastre en el loop** — reemplazar desde
  `rows = db.execute(_TIMELINE_SQL, ...)` hasta la línea `_apply_card_carryover(db, buckets, today, current_key)`
  (inclusive) por:

```python
    rows = db.execute(_TIMELINE_SQL, {"user_id": user.id, "plan_id": plan_id}).mappings().all()

    current_key = today.strftime("%Y-%m")
    py, pm = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    prev_key = f"{py:04d}-{pm:02d}"
    prev_cards = {
        (r["source_id"], r["currency_id"]): r
        for r in rows
        if r["event_date"] is not None
        and r["source_type"] == "tarjeta_credito"
        and r["event_date"].strftime("%Y-%m") == prev_key
    }

    open_debts: list[TimelineEntryOut] = []
    buckets: dict[str, dict] = {}  # "YYYY-MM" -> {"incomes", "expenses", "pi", "pe"}

    for r in rows:
        if r["event_date"] is None:
            open_debts.append(TimelineEntryOut(**_entry_fields(r)))
            continue
        key = r["event_date"].strftime("%Y-%m")
        b = buckets.setdefault(key, {"incomes": [], "expenses": [], "pi": Decimal("0"), "pe": Decimal("0")})
        amount = r["amount"]
        amount_converted = r["amount_converted"]
        minimum_payment = r["minimum_payment"]
        if key == current_key and r["source_type"] == "tarjeta_credito":
            p = prev_cards.get((r["source_id"], r["currency_id"]))
            if p is not None:
                carry = monthly_carry(p["amount"], p["paid_real"], p["minimum_payment"], p["financing_rate"], p["overdue_rate"])
                if carry > 0:
                    amount = amount + carry
                    amount_converted = amount_converted + carry * _rate(db, r["currency_id"], r["event_date"])
                    minimum_payment = (amount * PROJECTED_MINIMUM_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        eff_pa, eff_pac = _effective_planned(r["planned_amount"], r["planned_amount_converted"], amount, amount_converted)
        fields = _entry_fields(r)
        fields["amount"] = amount
        fields["amount_converted"] = amount_converted
        fields["minimum_payment"] = minimum_payment
        fields["planned_amount"] = eff_pa
        fields["planned_amount_converted"] = eff_pac
        entry = MonthEntryOut(event_date=r["event_date"], **fields)
        pending = eff_pac - r["paid_real_converted"]
        if r["is_income"]:
            b["incomes"].append(entry)
            b["pi"] += pending
        else:
            b["expenses"].append(entry)
            b["pe"] += pending

    months: list[MonthOut] = []
```

(Antes había `current_key = today.strftime("%Y-%m")` y `_apply_card_carryover(...)` justo antes de
`months: list[MonthOut] = []`; ahora `current_key`/`prev_cards` están arriba y el post-paso se eliminó.)

- [ ] **Step 6: Filtrar `amount == 0`** — en el `MonthOut.append`, cambiar:

```python
                incomes=b["incomes"],
                expenses=b["expenses"],
```
por:

```python
                incomes=[e for e in b["incomes"] if e.amount != 0],
                expenses=[e for e in b["expenses"] if e.amount != 0],
```

Y el `return`:

```python
    return TimelineOut(months=months, open_debts=[e for e in open_debts if e.amount != 0])
```

- [ ] **Step 7: Run los 4 tests → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_carryover_adds_prev_unpaid_to_current_month tests/test_get_cash_flow_entries.py::test_carryover_skips_when_prev_settled tests/test_get_cash_flow_entries.py::test_carryover_partial_plan_keeps_planned tests/test_get_cash_flow_entries.py::test_zero_amount_rows_hidden -q
```

Expected: PASS.

- [ ] **Step 8: Run el archivo completo → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q
```

Expected: PASS. Si algún test asume una row con `amount 0` visible, ajustarlo (ahora se ocultan); los que usan
montos > 0 no cambian.

- [ ] **Step 9: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_entry_service.py tests/test_get_cash_flow_entries.py && git commit -m "feat: plegar el arrastre de tarjeta en el loop + ocultar rows en 0"
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

- **Cobertura del spec:** §1 plegado (Steps 3-5: `_effective_planned` explícito, carry en el loop antes del
  efectivo, mínimo 15%, sin `_apply_card_carryover` ni hack de `pe`); §2 filtro `amount == 0` en meses y
  open_debts (Step 6); tests planned=amount, prev-saldado-oculto, plan-parcial, filtro (Step 1). ✓
- **Placeholder scan:** sin TBD/TODO; loop completo y tests con valores (810.80, 300.00, 121.62). ✓
- **Consistencia:** `_effective_planned` nueva firma usada con el `amount` arrastrado; `prev_cards`/`current_key`
  movidos antes del loop; pending sale de `eff_pac − paid_real` (sin doble conteo); filtro no toca `pi/pe`. ✓
- **Equivalencia:** caso sin plan → mismo `amount`/`pe` que el post-paso anterior; caso con plan parcial →
  planned = parte y pending sin duplicar (lo nuevo que se arregla). ✓
