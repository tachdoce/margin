# timeline — arrastre en cascada del saldo impago de tarjeta — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans o
> superpowers:subagent-driven-development. Steps con checkbox (`- [ ]`).

**Goal:** Reemplazar el arrastre de paso único por una **cascada** por (tarjeta, moneda): el saldo impago de un
mes (+interés) se suma al mes siguiente, mientras haya row, con `payment` = paid_real → plan explícito → `amount`
(pago total si no hay plan), auto-limitándose.

**Architecture:** Pre-pasada en `get_timeline` que recorre cada serie (tarjeta, moneda) en orden y calcula
`carry_in[row_id]` y el `minimum` recomputado; el loop existente aplica esos valores. `monthly_carry` renombra
su parámetro `paid_real` → `payment` (cálculo igual).

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Decimal · pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-carryover-cascade-design.md`

**Branch:** `feat/carryover-cascade`. Squash-merge al final. **No Notion. Sin web.**

**Higiene:** `cd .../backend && source .venv/bin/activate && pytest -q` (sin pipes/`2>&1`). Git planos. No push.

**Estado actual (verificado):** `get_timeline` calcula `current_key`/`prev_key`/`prev_cards` y, en el loop,
aplica el arrastre **solo** `if key == current_key` (paso único, usando `paid_real` del mes anterior). El loop
ya filtra `amount == 0` y usa `_effective_planned(planned, planned_conv, amount, amount_conv)`. `monthly_carry`
toma `(amount, paid_real, minimum_payment, financing_rate, overdue_rate)`. `PROJECTED_MINIMUM_RATE`, `_rate`,
`ROUND_HALF_UP`, `Decimal` importados.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/carryover-cascade
```

---

## Task 1: Cascada (TDD)

**Files:** `app/services/cash_flow/interest.py`, `app/services/cash_flow_entry_service.py`,
`tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Test nuevo (rojo)** — agregar a `tests/test_get_cash_flow_entries.py`:

```python
def test_carryover_cascades_through_planned_months(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user)
    # mayo: amount 1000, pagó 200 (>= mín 100 -> financiación 12) -> arrastra 810.80 a junio
    may = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 5, 29), is_income=False, amount=Decimal("1000.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("100.00"),
    )
    db_session.add(may)
    db_session.commit()
    db_session.refresh(may)
    _pay(db_session, may, amount="200.00")
    # junio: relleno, plan parcial 300 -> arrastra el resto a julio
    jun = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 6, 29), is_income=False, amount=Decimal("0.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("0.00"),
    )
    db_session.add(jun)
    db_session.commit()
    db_session.refresh(jun)
    _pay(db_session, jun, amount="300.00", plan_id=plan.id, planned_date=date(2026, 6, 29))
    # julio: relleno, sin plan -> absorbe (pago total), no arrastra
    db_session.add(CashFlowEntry(
        user_id=user.id, event_date=date(2026, 7, 29), is_income=False, amount=Decimal("0.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("0.00"),
    ))
    db_session.commit()
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun_row = next(e for e in next(m for m in out.months if m.month == "2026-06").expenses if str(e.source_id) == str(card.id))
    jul_row = next(e for e in next(m for m in out.months if m.month == "2026-07").expenses if str(e.source_id) == str(card.id))
    assert jun_row.amount == Decimal("810.80")          # arrastre de mayo
    assert jun_row.planned_amount == Decimal("300.00")  # plan parcial
    assert jul_row.amount == Decimal("517.70")          # cascada: resto de junio (510.80) + interés (6.90)
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_carryover_cascades_through_planned_months -q
```

Expected: FALLA (hoy el arrastre es de un solo paso; julio no recibe nada → `amount 0` y la row no aparece →
`StopIteration`).

- [ ] **Step 3: Renombrar el parámetro de `monthly_carry`** — en `app/services/cash_flow/interest.py`:

```python
def monthly_carry(amount, payment, minimum_payment, financing_rate, overdue_rate) -> Decimal:
    """Saldo impago + interés a arrastrar al mes siguiente (misma moneda). 0 si está saldado.

    Provisional: evolucionará. Tasa de financiación si el pago alcanzó el mínimo, mora si no.
    """
    balance = amount - payment
    if balance <= 0:
        return Decimal("0.00")
    paid_minimum = minimum_payment is not None and payment >= minimum_payment
    rate = financing_rate if paid_minimum else overdue_rate
    interest = balance * (rate / Decimal("100")) / Decimal("12") * HIDDEN_COST_FACTOR
    return (balance + interest).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

(Solo cambia el nombre del 2º parámetro; el cálculo es idéntico. Los tests de `monthly_carry` pasan posicional.)

- [ ] **Step 4: Reemplazar el pre-paso de un solo arrastre por la cascada** — en
  `app/services/cash_flow_entry_service.py`, reemplazar el bloque:

```python
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
```

por:

```python
    current_key = today.strftime("%Y-%m")

    # cascada del arrastre de tarjeta: por (tarjeta, moneda), en orden de event_date
    carry_in: dict = {}       # row id -> arrastre que se suma a esa row
    min_override: dict = {}   # row id -> minimum recomputado (15%) cuando hubo arrastre
    series: dict = {}
    for r in rows:
        if r["event_date"] is not None and r["source_type"] == "tarjeta_credito":
            series.setdefault((r["source_id"], r["currency_id"]), []).append(r)
    for serie in series.values():
        serie.sort(key=lambda r: r["event_date"])
        cin = Decimal("0")
        for r in serie:
            carry_in[r["id"]] = cin
            amount = r["amount"] + cin
            if r["paid_real"] > 0:
                payment = r["paid_real"]
            elif r["planned_amount"] > 0:
                payment = r["planned_amount"]
            else:
                payment = amount  # sin plan ni pago: se asume pago total -> no arrastra
            if cin > 0:
                minimum = (amount * PROJECTED_MINIMUM_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                min_override[r["id"]] = minimum
            else:
                minimum = r["minimum_payment"]
            cin = monthly_carry(amount, payment, minimum, r["financing_rate"], r["overdue_rate"])
```

- [ ] **Step 5: Aplicar `carry_in`/`min_override` en el loop** — reemplazar el bloque:

```python
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
```

por:

```python
        amount = r["amount"]
        amount_converted = r["amount_converted"]
        minimum_payment = r["minimum_payment"]
        cin = carry_in.get(r["id"], Decimal("0"))
        if cin > 0:
            amount = amount + cin
            amount_converted = amount_converted + cin * _rate(db, r["currency_id"], r["event_date"])
            minimum_payment = min_override[r["id"]]
```

- [ ] **Step 6: Run el test nuevo → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_carryover_cascades_through_planned_months -q
```

Expected: PASS.

- [ ] **Step 7: Run el archivo completo → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py tests/test_interest.py -q
```

Expected: PASS. Los tests existentes siguen verdes: `adds` (mayo→junio, junio sin plan absorbe → mismos
810.80/121.62/pending 810.80), `skips` (saldado → 0 oculto), `partial_plan` (junio plan 300, sin julio en la
serie → no cambia), `zero_hidden` (sin arrastre → oculto). Si alguno asume el comportamiento de paso único en
un caso multi-mes, ajustar al modelo de cascada.

- [ ] **Step 8: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow/interest.py app/services/cash_flow_entry_service.py tests/test_get_cash_flow_entries.py && git commit -m "feat: arrastre de tarjeta en cascada (mes sin plan asume pago total)"
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

- **Cobertura del spec:** §1 cascada por serie con `payment` = paid_real → plan → amount (Step 4); §2 aplicación
  en el loop (Step 5); `monthly_carry` rename (Step 3); auto-límite (mes sin plan ⇒ payment=amount ⇒ saldo 0).
  ✓
- **Placeholder scan:** sin TBD/TODO; pre-pasada y test con valores calculados (810.80; 510.80+6.90=517.70). ✓
- **Consistencia:** `carry_in`/`min_override` por `row.id`; `min_override` solo se setea y se lee con `cin > 0`;
  `monthly_carry(amount, payment, …)` posicional; `_effective_planned` y `pending` operan sobre el `amount`
  arrastrado; el filtro `amount == 0` ya existente oculta las rows sin arrastre. ✓
- **Equivalencia:** caso de un paso (mayo→junio, junio sin plan) da el mismo resultado que antes; lo nuevo es
  el encadenado cuando hay planes/pagos parciales consecutivos. ✓
