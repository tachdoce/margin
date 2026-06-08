# CashFlowEngine.expenses (motor) — Plan de implementación

> **For agentic workers:** Ejecutar según el modo que elija el usuario (inline o subagente con higiene de
> comandos: `cd` no `git -C`, sin `2>&1`). TDD: test → rojo → implementación → verde → commit por task.

**Goal:** Crear `materialize_expense` — el motor que materializa `cash_flow_entries` desde `obligations` de
kind `gasto`. Solo el motor; sin endpoints.

**Architecture:** Espeja `materialize_income` (`app/services/cash_flow/incomes.py`): UPSERT contra clave
lógica `(source_type='gasto', source_id, año, mes, currency_id)`, borrado de stale futuras sin pago real,
`today`/`horizon` inyectables, `SELECT ... FOR UPDATE` sobre la obligación, `flush` sin commit. Diferencias:
gate `is_ready` (no-op), `is_closed` → objetivo vacío, gasto único = 1 fila, y raise si tuviera que borrar
una entry futura con pago real.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, pytest. Spec:
`docs/superpowers/specs/2026-06-08-cashflowengine-expenses-design.md`.

**Rama:** `feat/cashflow-expenses` → squash-merge a `main`.

---

## Task 0: Crear la rama

- [ ] **Step 1:**

```bash
git checkout -b feat/cashflow-expenses
```

---

## Task 1: Motor `materialize_expense` + tests

**Files:**
- Create: `backend/app/services/cash_flow/expenses.py`
- Test: `backend/tests/test_cashflow_expenses.py`

- [ ] **Step 1: Escribir los tests (rojo)**

`backend/tests/test_cashflow_expenses.py`:

```python
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.plan import Plan
from app.models.priority_level import PriorityLevel
from app.models.user import User
from app.services.cash_flow.expenses import materialize_expense

TODAY = date(2026, 6, 1)
HORIZON = date(2026, 12, 31)  # jun..dic = 7 meses


@pytest.fixture
def user(db_session, seed_uy_currency):
    db_session.add_all(
        [
            PriorityLevel(level=2, name="Esencial", description="x"),
            PriorityLevel(level=3, name="Crítica", description="x"),
        ]
    )
    db_session.flush()
    db_session.add(
        ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                       description="x", default_priority_level=2, visible=True)
    )
    db_session.flush()
    u = User(country_code="UY")
    db_session.add(u)
    db_session.flush()
    return u


def _gasto(db_session, user, **overrides):
    kwargs = dict(
        user_id=user.id,
        obligation_type_id=1,
        priority_level=2,
        currency_id=1,
        amount=Decimal("12000.00"),
        is_monthly_recurring=True,
        due_day=10,
        first_due_date=None,
        shift_weekends=False,
        rates_add_vat=True,
        is_closed=False,
        review_findings="[]",
        is_ready=True,
    )
    kwargs.update(overrides)
    o = Obligation(**kwargs)
    db_session.add(o)
    db_session.flush()
    return o


def _entries(db_session, obligation_id):
    return list(
        db_session.execute(
            select(CashFlowEntry)
            .where(CashFlowEntry.source_type == "gasto", CashFlowEntry.source_id == obligation_id)
            .order_by(CashFlowEntry.event_date)
        ).scalars()
    )


def test_recurrente_materializa_por_mes(db_session, user):
    o = _gasto(db_session, user, due_day=10)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 7
    for e in entries:
        assert e.is_income is False
        assert e.source_type == "gasto"
        assert e.amount == Decimal("12000.00")
        assert e.currency_id == 1
        assert e.financing_rate is None and e.overdue_rate is None
        assert e.event_date.day == 10
    assert entries[0].event_date == date(2026, 6, 10)
    assert entries[-1].event_date == date(2026, 12, 10)


def test_unico_una_sola_entry(db_session, user):
    o = _gasto(db_session, user, is_monthly_recurring=False, due_day=None,
               first_due_date=date(2026, 8, 15))
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 15)


def test_gate_not_ready_no_materializa(db_session, user):
    o = _gasto(db_session, user, is_ready=False)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_gate_not_ready_deja_existentes_intactas(db_session, user):
    o = _gasto(db_session, user)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert len(_entries(db_session, o.id)) == 7
    # ahora se "rompe" el gate y cambia el monto: no debe tocar nada
    o.is_ready = False
    o.amount = Decimal("99999.00")
    db_session.flush()
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 7
    assert all(e.amount == Decimal("12000.00") for e in entries)


def test_is_closed_borra_futuras(db_session, user):
    o = _gasto(db_session, user)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert len(_entries(db_session, o.id)) == 7
    o.is_closed = True
    db_session.flush()
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_recurrente_a_unico_reconcilia(db_session, user):
    o = _gasto(db_session, user, due_day=10)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    agosto = next(e for e in _entries(db_session, o.id) if e.event_date.month == 8)
    agosto_id = agosto.id
    # pasa a único en agosto: misma clave (2026,8) → UPDATE in place, borra los otros 6
    o.is_monthly_recurring = False
    o.due_day = None
    o.first_due_date = date(2026, 8, 15)
    db_session.flush()
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].id == agosto_id
    assert entries[0].event_date == date(2026, 8, 15)


def test_pago_real_stale_lanza_excepcion(db_session, user):
    o = _gasto(db_session, user)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    fut = _entries(db_session, o.id)[0]  # futura
    db_session.add(CashFlowPayment(cash_flow_entry_id=fut.id, amount=Decimal("5000.00")))  # plan_id=None → real
    db_session.flush()
    o.is_closed = True  # vuelve stale a todas las futuras
    db_session.flush()
    with pytest.raises(RuntimeError):
        materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)


def test_pago_planificado_stale_se_borra(db_session, user):
    o = _gasto(db_session, user)
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    fut = _entries(db_session, o.id)[0]
    plan = Plan(user_id=user.id, name="P", is_default=False, is_engine_generated=False,
                selected_at=datetime.now(timezone.utc), dial_amount=Decimal("0"),
                dial_currency_id=1, goal_kind=None, goal_amount=None, goal_currency_id=None)
    db_session.add(plan)
    db_session.flush()
    db_session.add(CashFlowPayment(cash_flow_entry_id=fut.id, amount=Decimal("5000.00"), plan_id=plan.id))
    db_session.flush()
    o.is_closed = True
    db_session.flush()
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_pasado_no_se_toca(db_session, user):
    o = _gasto(db_session, user)
    # entry pasada del mismo gasto, fuera del objetivo
    past = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 3, 10), is_income=False,
        amount=Decimal("12000.00"), currency_id=1, source_type="gasto", source_id=o.id,
    )
    db_session.add(past)
    db_session.flush()
    past_id = past.id
    materialize_expense(db_session, o.id, today=TODAY, horizon=HORIZON)
    ids = {e.id for e in _entries(db_session, o.id)}
    assert past_id in ids  # no se borró
    assert len(ids) == 8  # 7 futuras + 1 pasada


def test_shift_weekends_corre_finde(db_session, user):
    # 2026-06-06 es sábado; con shift → lunes 2026-06-08
    o = _gasto(db_session, user, due_day=6, shift_weekends=True)
    materialize_expense(db_session, o.id, today=TODAY, horizon=date(2026, 6, 30))
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 6, 8)
```

- [ ] **Step 2: Correr los tests, verificar que fallan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_expenses.py -q
```
Esperado: FAIL (ModuleNotFoundError: app.services.cash_flow.expenses).

- [ ] **Step 3: Implementar el motor**

`backend/app/services/cash_flow/expenses.py`:

```python
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.services.cash_flow.date_utils import compute_event_date

HORIZON = date(2027, 12, 31)


def _iter_months(start_year: int, start_month: int, end_year: int, end_month: int):
    """(año, mes) desde (start) hasta (end) inclusive."""
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _target_event_dates(obligation: Obligation, today: date, horizon: date) -> list[date]:
    """event_date de cada entry que el gasto debería tener. Vacío si está cerrado."""
    if obligation.is_closed:
        return []

    dates: list[date] = []
    if obligation.is_monthly_recurring:
        for y, m in _iter_months(today.year, today.month, horizon.year, horizon.month):
            ed = compute_event_date(y, m, obligation.due_day, obligation.shift_weekends)
            if today <= ed <= horizon:
                dates.append(ed)
    else:
        fdd = obligation.first_due_date
        ed = compute_event_date(fdd.year, fdd.month, fdd.day, obligation.shift_weekends)
        if today <= ed <= horizon:
            dates.append(ed)
    return dates


def materialize_expense(
    db: Session, obligation_id: uuid.UUID, *, today: date | None = None, horizon: date = HORIZON
) -> None:
    """(Re)materializa las cash_flow_entries de una obligación-gasto por UPSERT contra su clave lógica
    (año, mes, currency_id). Gate: si is_ready es False, no-op. No hace commit (lo controla el caller)."""
    if today is None:
        today = date.today()

    obligation = db.execute(
        select(Obligation).where(Obligation.id == obligation_id).with_for_update()
    ).scalar_one_or_none()
    if obligation is None:
        return
    if not obligation.is_ready:
        return  # gate: no-op silencioso (no materializa, no borra)

    targets = _target_event_dates(obligation, today, horizon)

    existing = list(
        db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "gasto",
                CashFlowEntry.source_id == obligation.id,
            )
        ).scalars()
    )
    by_key = {(e.event_date.year, e.event_date.month, e.currency_id): e for e in existing}

    target_keys: set[tuple[int, int, int]] = set()
    for ed in targets:
        key = (ed.year, ed.month, obligation.currency_id)
        target_keys.add(key)
        entry = by_key.get(key)
        if entry is not None:
            entry.amount = obligation.amount
            entry.event_date = ed
        else:
            db.add(
                CashFlowEntry(
                    user_id=obligation.user_id,
                    event_date=ed,
                    is_income=False,
                    amount=obligation.amount,
                    currency_id=obligation.currency_id,
                    source_type="gasto",
                    source_id=obligation.id,
                )
            )

    # borrar las existentes fuera del objetivo: solo futuras (event_date >= today).
    # Si una futura stale tiene pago REAL (plan_id IS NULL) → no se borra: raise (rollback).
    stale = [e for key, e in by_key.items() if key not in target_keys]
    if stale:
        paid_ids = set(
            db.execute(
                select(CashFlowPayment.cash_flow_entry_id).where(
                    CashFlowPayment.cash_flow_entry_id.in_([e.id for e in stale]),
                    CashFlowPayment.plan_id.is_(None),
                )
            ).scalars()
        )
        for e in stale:
            if e.event_date is not None and e.event_date >= today:
                if e.id in paid_ids:
                    raise RuntimeError(
                        f"materialize_expense: invariante violado, "
                        f"entry {e.id} con pago real quedó fuera del objetivo"
                    )
                db.delete(e)

    db.flush()
```

- [ ] **Step 4: Correr los tests, verificar que pasan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_expenses.py -q
```
Esperado: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cash_flow/expenses.py backend/tests/test_cashflow_expenses.py
git commit -m "feat: CashFlowEngine.expenses (motor)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Suite completa

- [ ] **Step 1:**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```
Esperado: PASS (todo verde, +10 nuevos).

---

## Cierre

Tras Task 2 verde: **finishing-a-development-branch** → squash-merge `feat/cashflow-expenses` a `main` →
push (manual/prompteado).
