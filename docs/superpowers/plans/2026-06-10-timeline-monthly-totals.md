# Timeline Monthly Totals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** En `GET /cash-flow-entries` (timeline), por cada mes: `planned_amount` efectivo por row, totales pendientes (`pending_income`/`pending_expenses`), y `available` + `remaining_spending` + `balance` acumulado.

**Architecture:** Todo en `cash_flow_entry_service.get_timeline` (Python, sin tocar el SQL) + el schema `MonthOut`. Derivado en read, nada persistido. Se agrega `today: date | None = None` a `get_timeline` para tests deterministas. Las 3 partes se implementan incrementalmente; los tests viejos tienen `dial=0` y sin `cash_balances`, así que sus asserts de `balance` sobreviven (con `available=0`/`remaining_spending=0`, `balance` se reduce a `pending_income − pending_expenses`).

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest.

**Spec:** [docs/superpowers/specs/2026-06-10-timeline-monthly-totals-design.md](../specs/2026-06-10-timeline-monthly-totals-design.md)

**Branch:** ya estás en `feat/timeline-monthly-totals` (el spec ya está commiteado ahí). Squash-merge al final. **No tocar Notion.**

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`. Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## File Structure

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow_entry_service.py` | helper `_effective_planned`; `get_timeline` (param `today`, efectivo, pendientes, available/dial/balance); helpers `_rate`/`_available_now` |
| `app/schemas/cash_flow_entry.py` | `MonthOut`: rename totales + 2 campos nuevos + reorden |
| `tests/test_get_cash_flow_entries.py` | actualizar tests que rompen + tests nuevos de las 3 partes |

---

## Task 1: Parte 1 — `planned_amount` efectivo por row

**Files:** `app/services/cash_flow_entry_service.py`, `tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Test nuevo (rojo)** — agregar a `tests/test_get_cash_flow_entries.py`:

```python
def test_planned_falls_back_to_amount_when_no_plan(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00")  # sin pago planificado
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert e["planned_amount"] == "6000.00"            # cae a amount
    assert e["planned_amount_converted"] == "6000.00"
```

- [ ] **Step 2: Run → rojo**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_planned_falls_back_to_amount_when_no_plan -q`
Expected: FALLA (`planned_amount == "0.00"`, todavía sin fallback).

- [ ] **Step 3: Helper `_effective_planned`** — agregar en `cash_flow_entry_service.py` arriba de `get_timeline` (después de `_entry_fields`):

```python
def _effective_planned(r):
    """Monto efectivo de la row: el planificado si lo hay, si no el proyectado (amount)."""
    if r["planned_amount"] > 0:
        return r["planned_amount"], r["planned_amount_converted"]
    return r["amount"], r["amount_converted"]
```

- [ ] **Step 4: Aplicar el efectivo en el branch de meses** — en `get_timeline`, reemplazar el bloque del `for r in rows` que construye `entry` (las rows con `event_date`) por:

```python
        eff_pa, eff_pac = _effective_planned(r)
        fields = _entry_fields(r)
        fields["planned_amount"] = eff_pa
        fields["planned_amount_converted"] = eff_pac
        entry = MonthEntryOut(event_date=r["event_date"], **fields)
        if r["is_income"]:
            b["incomes"].append(entry)
            b["ti"] += r["amount_converted"]
        else:
            b["expenses"].append(entry)
            b["te"] += r["amount_converted"]
```

(El branch de `open_debts` —`if r["event_date"] is None`— queda igual: usa `_entry_fields(r)` sin override, así NO recibe el fallback.)

- [ ] **Step 5: Run → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_planned_falls_back_to_amount_when_no_plan -q`
Expected: PASS.

- [ ] **Step 6: Actualizar test que cambia de expectativa** — en `test_planned_of_other_plan_excluded`, la row no tiene pago planificado de SU plan → ahora cae a `amount`. Cambiar la última línea:

```python
    assert e["planned_amount"] == "6000.00"  # sin planificado de este plan → cae a amount (el 999 de otro plan sigue excluido)
```

- [ ] **Step 7: Open_debt sin fallback** — en `test_open_debt_madre_in_open_debts`, agregar tras `assert od["amount"] == "30000.00"`:

```python
    assert od["planned_amount"] == "0.00"  # las open_debts NO reciben el fallback
```

- [ ] **Step 8: Run el archivo completo → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q`
Expected: PASS (los totales siguen en `total_income`/`total_expenses`, sin tocar todavía).

- [ ] **Step 9: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_entry_service.py tests/test_get_cash_flow_entries.py && git commit -m "feat: planned_amount efectivo por row en el timeline"
```

---

## Task 2: Parte 2 — totales pendientes + rename

**Files:** `app/schemas/cash_flow_entry.py`, `app/services/cash_flow_entry_service.py`, `tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Test nuevo (rojo)** — agregar (llama al service directo para fijar nada de `today`; igual no depende de `today`):

```python
from app.services import cash_flow_entry_service as svc


def test_pending_nets_paid_real(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)  # dial 0
    e = _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00")
    _pay(db_session, e, amount="2000.00")  # pago real
    out = svc.get_timeline(db_session, user, plan.id)
    jun = out.months[0]
    assert jun.pending_expenses == Decimal("4000.00")  # efectivo 6000 − paid_real 2000
```

- [ ] **Step 2: Run → rojo**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_pending_nets_paid_real -q`
Expected: FALLA (`AttributeError: ... 'pending_expenses'` — el schema aún tiene `total_expenses`).

- [ ] **Step 3: Renombrar en el schema** — en `app/schemas/cash_flow_entry.py`, `MonthOut`:

```python
class MonthOut(BaseModel):
    month: str
    pending_income: Decimal
    pending_expenses: Decimal
    balance: Decimal
    incomes: list[MonthEntryOut]
    expenses: list[MonthEntryOut]
```

- [ ] **Step 4: Acumular pendiente en el service** — en `get_timeline`: cambiar la init de `buckets` y la acumulación.

Cambiar la línea del comentario/`setdefault`:

```python
        b = buckets.setdefault(key, {"incomes": [], "expenses": [], "pi": Decimal("0"), "pe": Decimal("0")})
```

Cambiar la acumulación dentro del `if r["is_income"]/else` (reemplaza las líneas `b["ti"] += ...`/`b["te"] += ...`):

```python
        pending = eff_pac - r["paid_real_converted"]
        if r["is_income"]:
            b["incomes"].append(entry)
            b["pi"] += pending
        else:
            b["expenses"].append(entry)
            b["pe"] += pending
```

Y el armado de `MonthOut` (por ahora `balance` = flujo pendiente; se redefine en Task 3):

```python
        months.append(
            MonthOut(
                month=key,
                pending_income=b["pi"],
                pending_expenses=b["pe"],
                balance=b["pi"] - b["pe"],
                incomes=b["incomes"],
                expenses=b["expenses"],
            )
        )
```

- [ ] **Step 5: Actualizar los tests que usan los nombres viejos.**

En `test_timeline_groups_by_month_and_flow`:

```python
    assert jun["pending_income"] == "45000.00"
    assert jun["pending_expenses"] == "6000.00"
    assert jun["balance"] == "39000.00"
```

En `test_open_debt_projected_into_month`, última línea:

```python
    assert jul["pending_expenses"] == "5000.00"
```

- [ ] **Step 6: Run el archivo → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/schemas/cash_flow_entry.py app/services/cash_flow_entry_service.py tests/test_get_cash_flow_entries.py && git commit -m "feat: totales pendientes (pending_income/pending_expenses) en el timeline"
```

---

## Task 3: Parte 3 — available + remaining_spending + balance acumulado

**Files:** `app/schemas/cash_flow_entry.py`, `app/services/cash_flow_entry_service.py`, `tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Tests nuevos (rojo)** — agregar helpers + 2 tests:

```python
def _cash(db_session, user, currency_id, amount):
    from app.models.cash_balance import CashBalance
    db_session.add(CashBalance(user_id=user.id, currency_id=currency_id, amount=Decimal(amount)))
    db_session.commit()


def _plan_dial(db_session, user, dial_amount):
    plan = Plan(
        user_id=user.id, name="Plan", is_default=False, is_engine_generated=False,
        selected_at=datetime.now(timezone.utc), dial_amount=Decimal(dial_amount), dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def test_available_dial_and_balance_first_month(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan_dial(db_session, user, "42000.00")
    _cash(db_session, user, 1, "38500.00")  # Peso (cotiza x1)
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 10), amount="90000.00")
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="91225.70")
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = out.months[0]
    assert jun.available == Decimal("38500.00")
    assert jun.remaining_spending == Decimal("29400.00")  # (30-9)/30 * 42000
    # balance = (38500 + 90000) − (91225.70 + 29400) = 7874.30
    assert jun.balance == Decimal("7874.30")


def test_available_carries_balance_to_next_month(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan_dial(db_session, user, "0")  # dial 0 aísla el arrastre
    _cash(db_session, user, 1, "10000.00")
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 10), amount="5000.00")   # junio
    _card_entry(db_session, user, event_date=date(2026, 7, 10), amount="3000.00")            # julio
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun, jul = out.months[0], out.months[1]
    assert jun.balance == Decimal("15000.00")      # (10000 + 5000) − (0 + 0)
    assert jul.available == Decimal("15000.00")    # arrastre
    assert jul.balance == Decimal("12000.00")      # (15000 + 0) − (3000 + 0)
```

- [ ] **Step 2: Run → rojo**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_available_dial_and_balance_first_month -q`
Expected: FALLA (`AttributeError ... 'available'` / `get_timeline() got an unexpected keyword argument 'today'`).

- [ ] **Step 3: Schema con los 2 campos nuevos + reorden** — en `app/schemas/cash_flow_entry.py`, `MonthOut`:

```python
class MonthOut(BaseModel):
    month: str
    available: Decimal
    pending_income: Decimal
    pending_expenses: Decimal
    remaining_spending: Decimal
    balance: Decimal
    incomes: list[MonthEntryOut]
    expenses: list[MonthEntryOut]
```

- [ ] **Step 4: Imports nuevos en el service** — en `cash_flow_entry_service.py`, agregar al tope:

```python
import calendar
from decimal import ROUND_HALF_UP

from app.models.cash_balance import CashBalance
from app.models.currency_rate import CurrencyRate
```

(`Decimal`, `date`, `select` ya están importados.)

- [ ] **Step 5: Helpers de cotización y disponible** — agregar en `cash_flow_entry_service.py` antes de `get_timeline`:

```python
def _rate(db: Session, currency_id: int, on_date: date) -> Decimal:
    r = db.get(CurrencyRate, (currency_id, on_date))
    return r.value if r is not None else Decimal("1")


def _available_now(db: Session, user: User, today: date) -> Decimal:
    total = Decimal("0")
    for cb in db.execute(select(CashBalance).where(CashBalance.user_id == user.id)).scalars():
        total += cb.amount * _rate(db, cb.currency_id, today)
    return total
```

- [ ] **Step 6: `today` + available/dial/balance en `get_timeline`.**

Cambiar la firma:

```python
def get_timeline(db: Session, user: User, plan_id: uuid.UUID | None, today: date | None = None) -> TimelineOut:
```

Tras validar el plan (después de `if plan is None or plan.user_id != user.id: raise ...`), agregar:

```python
    today = today or date.today()
    dial = plan.dial_amount * _rate(db, plan.dial_currency_id, today)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    remaining_days = days_in_month - (today.day - 1)
    dial_prorated = (dial * Decimal(remaining_days) / Decimal(days_in_month)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
```

Reemplazar el bloque que arma `months` por el arrastre (primer mes = cash + dial prorrateado; resto = balance previo + dial completo):

```python
    months: list[MonthOut] = []
    prev_balance: Decimal | None = None
    for i, key in enumerate(sorted(buckets)):
        b = buckets[key]
        b["incomes"].sort(key=lambda e: (e.event_date, str(e.id)))
        b["expenses"].sort(key=lambda e: (e.event_date, str(e.id)))
        if i == 0:
            available = _available_now(db, user, today)
            remaining_spending = dial_prorated
        else:
            available = prev_balance
            remaining_spending = dial
        balance = (available + b["pi"]) - (b["pe"] + remaining_spending)
        months.append(
            MonthOut(
                month=key,
                available=available,
                pending_income=b["pi"],
                pending_expenses=b["pe"],
                remaining_spending=remaining_spending,
                balance=balance,
                incomes=b["incomes"],
                expenses=b["expenses"],
            )
        )
        prev_balance = balance
```

- [ ] **Step 7: Run los tests nuevos → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_available_dial_and_balance_first_month tests/test_get_cash_flow_entries.py::test_available_carries_balance_to_next_month -q`
Expected: PASS.

- [ ] **Step 8: Run el archivo completo → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q`
Expected: PASS. Los tests viejos siguen verdes: `dial=0` y sin `cash_balances` ⇒ `available=0`, `remaining_spending=0` ⇒ `balance = pending_income − pending_expenses` (mismos valores).

- [ ] **Step 9: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/schemas/cash_flow_entry.py app/services/cash_flow_entry_service.py tests/test_get_cash_flow_entries.py && git commit -m "feat: available, remaining_spending y balance acumulado en el timeline"
```

---

## Task 4: Suite completa + cierre

- [ ] **Step 1: Suite completa**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q`
Expected: todo verde.

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado: **squash-merge** de `feat/timeline-monthly-totals` a `main` (1 commit). Push **manual**. (No tocar Notion.)

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** Parte 1 efectivo (Task 1); Parte 2 pendientes + rename (Task 2); Parte 3 available/remaining_spending/balance + `today` (Task 3). Schema `MonthOut` reordenado (Task 3). ✓
- **Placeholder scan:** sin TBD/TODO; todo el código está escrito. ✓
- **Consistencia de tipos/nombres:** `_effective_planned` (Task 1) reusado en Task 2/3; `pending_income`/`pending_expenses`/`available`/`remaining_spending`/`balance` consistentes entre schema y service; `_rate`/`_available_now`/`dial`/`dial_prorated` definidos antes de usarse. ✓
- **Tests viejos:** los renames (Task 2) y la redefinición de `balance` (Task 3) no rompen porque `dial=0` y sin `cash_balances` ⇒ `balance` se reduce al flujo. `test_planned_of_other_plan_excluded` y `test_open_debt_madre_in_open_debts` actualizados en Task 1. ✓
- **Sin Notion** en el cierre. ✓
```