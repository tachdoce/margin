# timeline — arrastre del saldo impago de tarjeta + interés — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans o
> superpowers:subagent-driven-development. Steps con checkbox (`- [ ]`).

**Goal:** En `get_timeline`, el saldo impago del mes anterior de una tarjeta (por moneda) se arrastra al mes
actual con interés (función encapsulada), sumándose al `amount` de la row y al `pending_expenses` del mes.

**Architecture:** Función pura `monthly_carry` en `app/services/cash_flow/interest.py` + constante
`HIDDEN_COST_FACTOR`. Segunda pasada `_apply_card_carryover` en `get_timeline`, tras armar los buckets y antes
del loop de meses. Read-time, nada persistido.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Decimal · pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-credit-card-carryover-interest-design.md`

**Branch:** `feat/credit-card-carryover-interest`. Squash-merge al final. **No Notion. Sin web.**

**Higiene:** `cd .../backend && source .venv/bin/activate && pytest -q` (sin pipes/`2>&1`). Git planos. No push.

**Estado actual (verificado):** `get_timeline` arma `buckets["YYYY-MM"] = {"incomes","expenses","pi","pe"}` en
el row loop; luego `current_key = today.strftime("%Y-%m")` y el loop de meses (`pending_expenses = b["pe"]`). Las
rows son `MonthEntryOut` (mutables) con `amount`, `paid_real`, `minimum_payment`, `financing_rate`,
`overdue_rate`, `source_type`, `source_id`, `currency_id`, `event_date`, `amount_converted`. `_rate(db, cid,
on_date)` existe. `app/services/cash_flow/constants.py` tiene `PROJECTED_MINIMUM_RATE`.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/credit-card-carryover-interest
```

---

## Task 1: Función `monthly_carry` (TDD)

**Files:** `app/services/cash_flow/constants.py`, `app/services/cash_flow/interest.py`, `tests/test_interest.py`

- [ ] **Step 1: Test (rojo)** — crear `tests/test_interest.py`:

```python
from decimal import Decimal

from app.services.cash_flow.interest import monthly_carry


def test_carry_overdue_when_minimum_unpaid():
    # pagó 74 < mínimo 93.93 -> mora 18.30; saldo 504.76; interés 504.76*0.183/12*1.35 = 10.39
    assert monthly_carry(Decimal("578.76"), Decimal("74"), Decimal("93.93"), Decimal("14.64"), Decimal("18.30")) == Decimal("515.15")


def test_carry_financing_when_minimum_paid():
    # saldo 800, pagó 200 >= mínimo 100 -> financiación 12%; interés 800*0.12/12*1.35 = 10.80
    assert monthly_carry(Decimal("1000"), Decimal("200"), Decimal("100"), Decimal("12"), Decimal("24")) == Decimal("810.80")


def test_carry_zero_when_settled():
    assert monthly_carry(Decimal("500"), Decimal("500"), Decimal("100"), Decimal("12"), Decimal("24")) == Decimal("0.00")


def test_carry_none_minimum_is_overdue():
    # minimum None -> mora 24%; saldo 800; interés 800*0.24/12*1.35 = 21.60
    assert monthly_carry(Decimal("1000"), Decimal("200"), None, Decimal("12"), Decimal("24")) == Decimal("821.60")
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_interest.py -q
```

Expected: FALLA (`ModuleNotFoundError: app.services.cash_flow.interest`).

- [ ] **Step 3: Constante** — en `app/services/cash_flow/constants.py`, agregar:

```python
# Factor de gastos ocultos de tarjeta (provisional): infla el interés mensual.
HIDDEN_COST_FACTOR = Decimal("1.35")
```

- [ ] **Step 4: Función** — crear `app/services/cash_flow/interest.py`:

```python
from decimal import ROUND_HALF_UP, Decimal

from app.services.cash_flow.constants import HIDDEN_COST_FACTOR


def monthly_carry(amount, paid_real, minimum_payment, financing_rate, overdue_rate) -> Decimal:
    """Saldo impago + interés a arrastrar al mes siguiente (misma moneda). 0 si está saldado.

    Provisional: evolucionará. Tasa de financiación si se pagó el mínimo, mora si no.
    """
    balance = amount - paid_real
    if balance <= 0:
        return Decimal("0.00")
    paid_minimum = minimum_payment is not None and paid_real >= minimum_payment
    rate = financing_rate if paid_minimum else overdue_rate
    interest = balance * (rate / Decimal("100")) / Decimal("12") * HIDDEN_COST_FACTOR
    return (balance + interest).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_interest.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow/constants.py app/services/cash_flow/interest.py tests/test_interest.py && git commit -m "feat: monthly_carry (saldo impago + interés de tarjeta)"
```

---

## Task 2: Arrastre en `get_timeline` (TDD)

**Files:** `app/services/cash_flow_entry_service.py`, `tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Tests (rojo)** — agregar a `tests/test_get_cash_flow_entries.py`:

```python
def test_carryover_adds_prev_unpaid_to_current_month(client, db_session, seed_cc_refs):
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
    _pay(db_session, prev, amount="200.00")  # pago real: 200 >= mínimo 100 -> financiación
    db_session.add(CashFlowEntry(
        user_id=user.id, event_date=date(2026, 6, 29), is_income=False, amount=Decimal("0.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("0.00"),
    ))
    db_session.commit()
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = next(m for m in out.months if m.month == "2026-06")
    row = next(e for e in jun.expenses if str(e.source_id) == str(card.id))
    assert row.amount == Decimal("810.80")            # 0 + arrastre (saldo 800 + interés 10.80)
    assert row.minimum_payment == Decimal("121.62")   # 810.80 * 0.15 (mínimo del mes sobre el amount arrastrado)
    assert jun.pending_expenses == Decimal("810.80")  # el arrastre sube el pendiente (Peso, cotiza x1)


def test_carryover_skips_when_prev_settled(client, db_session, seed_cc_refs):
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
    _pay(db_session, prev, amount="1000.00")  # saldado
    db_session.add(CashFlowEntry(
        user_id=user.id, event_date=date(2026, 6, 29), is_income=False, amount=Decimal("0.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("0.00"),
    ))
    db_session.commit()
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = next(m for m in out.months if m.month == "2026-06")
    row = next(e for e in jun.expenses if str(e.source_id) == str(card.id))
    assert row.amount == Decimal("0.00")  # mes anterior saldado -> sin arrastre
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_carryover_adds_prev_unpaid_to_current_month -q
```

Expected: FALLA (`row.amount == 0.00`, todavía sin arrastre).

- [ ] **Step 3: Imports** — en `app/services/cash_flow_entry_service.py`, con los imports de servicios:

```python
from app.services.cash_flow.constants import PROJECTED_MINIMUM_RATE
from app.services.cash_flow.interest import monthly_carry
```

- [ ] **Step 4: Helper `_apply_card_carryover`** — agregar antes de `get_timeline` (p. ej. después de
  `_available_now`):

```python
def _apply_card_carryover(db: Session, buckets: dict, today: date, current_key: str) -> None:
    """Suma a las rows de tarjeta del mes actual el saldo impago + interés del mes anterior
    (misma tarjeta y moneda). Sube el amount/amount_converted de la row y el pending (pe) del mes."""
    py, pm = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    prev_key = f"{py:04d}-{pm:02d}"
    cur = buckets.get(current_key)
    prev = buckets.get(prev_key)
    if cur is None or prev is None:
        return
    prev_cards = {
        (e.source_id, e.currency_id): e
        for e in prev["expenses"]
        if e.source_type == "tarjeta_credito"
    }
    for row in cur["expenses"]:
        if row.source_type != "tarjeta_credito":
            continue
        p = prev_cards.get((row.source_id, row.currency_id))
        if p is None:
            continue
        carry = monthly_carry(p.amount, p.paid_real, p.minimum_payment, p.financing_rate, p.overdue_rate)
        if carry <= 0:
            continue
        carry_conv = carry * _rate(db, row.currency_id, row.event_date)
        row.amount += carry
        row.amount_converted += carry_conv
        row.minimum_payment = (row.amount * PROJECTED_MINIMUM_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cur["pe"] += carry_conv
```

(El `minimum_payment` del mes se recomputa al 15% del `amount` arrastrado — misma constante que el motor.)

- [ ] **Step 5: Llamar al helper** — en `get_timeline`, reemplazar:

```python
    current_key = today.strftime("%Y-%m")
    months: list[MonthOut] = []
```

por:

```python
    current_key = today.strftime("%Y-%m")
    _apply_card_carryover(db, buckets, today, current_key)
    months: list[MonthOut] = []
```

- [ ] **Step 6: Run los tests nuevos → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_carryover_adds_prev_unpaid_to_current_month tests/test_get_cash_flow_entries.py::test_carryover_skips_when_prev_settled -q
```

Expected: PASS.

- [ ] **Step 7: Run el archivo → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q
```

Expected: PASS (cambio acotado al mes actual con par anterior de tarjeta; los demás tests no tienen ese par).

- [ ] **Step 8: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_entry_service.py tests/test_get_cash_flow_entries.py && git commit -m "feat: timeline arrastra el saldo impago de tarjeta + interés al mes actual"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde.

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: superpowers:finishing-a-development-branch. **squash-merge** a
  `main` (1 commit). Push **manual**. Sin Notion.

---

## Self-Review

- **Cobertura del spec:** §2 función (Task 1: constante + `monthly_carry` + unit, incl. mínimo None y saldado);
  §1/§3 arrastre en `get_timeline` (Task 2: helper + llamada, sube amount/amount_converted y `pe`); matcheo por
  `(source_id, currency_id)` del mes calendario anterior. ✓
- **Placeholder scan:** sin TBD/TODO; función, helper y tests con valores calculados (504.76→515.15;
  800→810.80; 0.00; None→821.60). ✓
- **Consistencia:** `HIDDEN_COST_FACTOR` en constants, importado por interest; `monthly_carry` importado en el
  service; `_rate`/`MonthEntryOut` mutable; `pending_expenses = b["pe"]` ⇒ sumar a `pe` lo refleja. ✓
- **Acotado:** solo mes actual ↔ anterior, solo `tarjeta_credito`, un paso; tests Peso (cotiza x1) evitan
  sembrar cotización. ✓
