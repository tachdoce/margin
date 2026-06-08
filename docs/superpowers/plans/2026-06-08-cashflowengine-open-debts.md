# CashFlowEngine.open_debts (motor) — Plan de implementación

> **For agentic workers:** Ejecutar según el modo que elija el usuario (inline o subagente con higiene de
> comandos: `cd` no `git -C`, sin `2>&1`). TDD: test → rojo → implementación → verde → commit por task.

**Goal:** Crear `materialize_open_debt` — materializa 1 `cash_flow_entries` atemporal (event_date NULL)
desde `obligations` de kind `deuda_abierta`. Solo el motor; sin endpoints.

**Architecture:** El más simple de la familia: gate `is_ready`, `SELECT ... FOR UPDATE` sobre la
obligación, UPSERT de la única fila por clave `(source_type='deuda_abierta', source_id)`. Sin proyección,
sin fechas, sin borrado de stale, sin branch de `is_closed`. `flush` sin commit.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, pytest. Spec:
`docs/superpowers/specs/2026-06-08-cashflowengine-open-debts-design.md`.

**Rama:** `feat/cashflow-open-debts` → squash-merge a `main`.

---

## Task 0: Crear la rama

- [ ] **Step 1:**

```bash
git checkout -b feat/cashflow-open-debts
```

---

## Task 1: Motor `materialize_open_debt` + tests

**Files:**
- Create: `backend/app/services/cash_flow/open_debts.py`
- Test: `backend/tests/test_cashflow_open_debts.py`

- [ ] **Step 1: Escribir los tests (rojo)**

`backend/tests/test_cashflow_open_debts.py`:

```python
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.user import User
from app.services.cash_flow.open_debts import materialize_open_debt


@pytest.fixture
def user(db_session, seed_uy_currency):
    db_session.add(PriorityLevel(level=6, name="Ajustable", description="x"))
    db_session.flush()
    db_session.add(
        ObligationType(id=8, obligation_kind="deuda_abierta", code="informal", name="Informal",
                       description="x", default_priority_level=6, visible=True)
    )
    db_session.flush()
    u = User(country_code="UY")
    db_session.add(u)
    db_session.flush()
    return u


def _open_debt(db_session, user, **overrides):
    kwargs = dict(
        user_id=user.id,
        obligation_type_id=8,
        priority_level=6,
        currency_id=1,
        amount=Decimal("8000.00"),
        is_monthly_recurring=False,
        due_day=None,
        first_due_date=None,
        total_installments=None,
        financing_rate=None,
        overdue_rate=None,
        rates_add_vat=True,
        shift_weekends=False,
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
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "deuda_abierta",
                CashFlowEntry.source_id == obligation_id,
            )
        ).scalars()
    )


def test_materializa_una_fila(db_session, user):
    o = _open_debt(db_session, user)
    materialize_open_debt(db_session, o.id)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    e = entries[0]
    assert e.event_date is None
    assert e.is_income is False
    assert e.source_type == "deuda_abierta"
    assert e.amount == Decimal("8000.00")
    assert e.currency_id == 1
    assert e.financing_rate is None and e.overdue_rate is None


def test_idempotente_no_duplica(db_session, user):
    o = _open_debt(db_session, user)
    materialize_open_debt(db_session, o.id)
    materialize_open_debt(db_session, o.id)
    assert len(_entries(db_session, o.id)) == 1


def test_edita_amount_actualiza_misma_fila(db_session, user):
    o = _open_debt(db_session, user)
    materialize_open_debt(db_session, o.id)
    entry_id = _entries(db_session, o.id)[0].id
    o.amount = Decimal("3000.00")
    db_session.flush()
    materialize_open_debt(db_session, o.id)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].id == entry_id
    assert entries[0].amount == Decimal("3000.00")


def test_gate_not_ready_no_materializa(db_session, user):
    o = _open_debt(db_session, user, is_ready=False)
    materialize_open_debt(db_session, o.id)
    assert _entries(db_session, o.id) == []


def test_is_closed_no_borra(db_session, user):
    o = _open_debt(db_session, user)
    materialize_open_debt(db_session, o.id)
    entry_id = _entries(db_session, o.id)[0].id
    o.is_closed = True
    o.amount = Decimal("5000.00")  # la acción de cierre ajusta el total pagado
    db_session.flush()
    materialize_open_debt(db_session, o.id)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].id == entry_id
    assert entries[0].amount == Decimal("5000.00")


def test_no_toca_pagos(db_session, user):
    o = _open_debt(db_session, user)
    materialize_open_debt(db_session, o.id)
    e = _entries(db_session, o.id)[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=e.id, amount=Decimal("2000.00")))  # real
    db_session.flush()
    o.amount = Decimal("6000.00")
    db_session.flush()
    materialize_open_debt(db_session, o.id)
    pagos = list(
        db_session.execute(
            select(CashFlowPayment).where(CashFlowPayment.cash_flow_entry_id == e.id)
        ).scalars()
    )
    assert len(pagos) == 1
    assert _entries(db_session, o.id)[0].amount == Decimal("6000.00")
```

> Nota: agregar `import pytest` arriba del archivo (lo usa el decorador `@pytest.fixture`).

- [ ] **Step 2: Correr los tests, verificar que fallan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_open_debts.py -q
```
Esperado: FAIL (ModuleNotFoundError: app.services.cash_flow.open_debts).

- [ ] **Step 3: Implementar el motor**

`backend/app/services/cash_flow/open_debts.py`:

```python
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.obligation import Obligation


def materialize_open_debt(db: Session, obligation_id: uuid.UUID) -> None:
    """(Re)materializa la única cash_flow_entries (atemporal, event_date NULL) de una obligación
    deuda_abierta. Gate: is_ready False → no-op. Nunca borra. No hace commit (lo controla el caller)."""
    obligation = db.execute(
        select(Obligation).where(Obligation.id == obligation_id).with_for_update()
    ).scalar_one_or_none()
    if obligation is None:
        return
    if not obligation.is_ready:
        return  # gate: no-op silencioso

    entry = db.execute(
        select(CashFlowEntry).where(
            CashFlowEntry.source_type == "deuda_abierta",
            CashFlowEntry.source_id == obligation.id,
        )
    ).scalar_one_or_none()

    if entry is not None:
        entry.amount = obligation.amount
        entry.currency_id = obligation.currency_id
    else:
        db.add(
            CashFlowEntry(
                user_id=obligation.user_id,
                event_date=None,
                is_income=False,
                amount=obligation.amount,
                currency_id=obligation.currency_id,
                financing_rate=None,
                overdue_rate=None,
                source_type="deuda_abierta",
                source_id=obligation.id,
            )
        )

    db.flush()
```

- [ ] **Step 4: Correr los tests, verificar que pasan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_open_debts.py -q
```
Esperado: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cash_flow/open_debts.py backend/tests/test_cashflow_open_debts.py
git commit -m "feat: CashFlowEngine.open_debts (motor)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Suite completa

- [ ] **Step 1:**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```
Esperado: PASS (todo verde, +6 nuevos).

---

## Cierre

Tras Task 2 verde: **finishing-a-development-branch** → squash-merge `feat/cashflow-open-debts` a `main` →
push (manual/prompteado).
