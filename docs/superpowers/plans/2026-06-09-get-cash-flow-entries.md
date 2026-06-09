# GET /cash-flow-entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `GET /cash-flow-entries?plan_id=` — la línea de tiempo del flujo de caja (entries reales + simuladas
del plan, agrupadas por mes y flujo, con `paid_real`/`planned_amount` derivados, proyección de `deuda_abierta`
y conversión a moneda legal).

**Architecture:** Router thin → service `get_timeline` que corre **una SQL cruda (`text()`)** con 4 CTEs
(espeja Notion) y arma el `TimelineOut` en Python. Read-only.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 (`text()`) · Pydantic v2 · pytest · Postgres.

**Spec:** `docs/superpowers/specs/2026-06-09-get-cash-flow-entries-design.md`

**Branch:** `feat/get-cash-flow-entries` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

**Patrones del repo (verificados):**
- `plan_id_required` y `not_found` YA existen en `errors.py` (reusar; **sin** códigos nuevos).
- Service: `(db, user, ...)`, `raise AppError(...)`. Este es read-only (sin commit).
- Pydantic v2 serializa `Decimal` como string (por eso el response usa schemas, no dicts).
- Modelos clave: `CashFlowEntry(id,user_id,event_date,is_income,amount,currency_id,source_type,source_id,...)`,
  `CashFlowPayment(...,plan_id,planned_date,created_at)`, `Plan(id,user_id,...)`,
  `PlanMovement(id,plan_id,kind,currency_id,principal_amount,start_date,rates_add_vat,...)`,
  `CreditCard(id,user_id,institution_id,card_network_id,current_limit,closing_day,due_day,4×rate,rates_add_vat,review_findings,is_ready,deleted_at)`,
  `CurrencyRate(currency_id,rate_date,value,is_projected)`.
- Fixtures: `seed_cc_refs` (UY + Peso id 1 + Institution id 1 "Scotiabank" + CreditCardNetwork id 1 "Amex" + …),
  `client`, `db_session`. Helpers de test: `_headers`/`_last_user` (ver slice de pagos).

---

## File Structure

| Archivo | Cambio |
|---|---|
| `app/schemas/cash_flow_entry.py` | `TimelineEntryOut`, `MonthEntryOut`, `MonthOut`, `TimelineOut` |
| `app/services/cash_flow_entry_service.py` | `get_timeline` (SQL `text()` + armador) |
| `app/routers/cash_flow_entries.py` | `GET /cash-flow-entries` |
| `app/main.py` | registrar el router |
| `tests/test_get_cash_flow_entries.py` | toda la batería |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/get-cash-flow-entries
```

---

## Task 1: Schemas + service + router + test base

**Files:**
- Create: `app/schemas/cash_flow_entry.py`, `app/services/cash_flow_entry_service.py`,
  `app/routers/cash_flow_entries.py`, `tests/test_get_cash_flow_entries.py`
- Modify: `app/main.py`

- [ ] **Step 1: Schemas** `app/schemas/cash_flow_entry.py`:

```python
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class TimelineEntryOut(BaseModel):
    id: uuid.UUID
    amount: Decimal
    paid_real: Decimal
    planned_amount: Decimal
    currency_id: int
    source_type: str
    source_id: uuid.UUID
    description: str | None
    amount_converted: Decimal
    paid_real_converted: Decimal
    planned_amount_converted: Decimal


class MonthEntryOut(TimelineEntryOut):
    event_date: date


class MonthOut(BaseModel):
    month: str
    total_income: Decimal
    total_expenses: Decimal
    balance: Decimal
    incomes: list[MonthEntryOut]
    expenses: list[MonthEntryOut]


class TimelineOut(BaseModel):
    months: list[MonthOut]
    open_debts: list[TimelineEntryOut]
```

- [ ] **Step 2: Service** `app/services/cash_flow_entry_service.py` (la SQL es copia literal de la página
  Notion `GET cash-flow-entries`):

```python
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.plan import Plan
from app.models.user import User
from app.schemas.cash_flow_entry import MonthEntryOut, MonthOut, TimelineEntryOut, TimelineOut

_TIMELINE_SQL = text(
    """
WITH entries AS (
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, o.description
  FROM cash_flow_entries cfe
  JOIN obligations o ON o.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type IN ('gasto', 'deuda', 'deuda_abierta')
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, i.description
  FROM cash_flow_entries cfe
  JOIN incomes i ON i.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type = 'ingreso'
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income, pm.description
  FROM cash_flow_entries cfe
  JOIN plan_movements pm ON pm.id = cfe.source_id
  WHERE cfe.user_id = :user_id
    AND cfe.source_type IN ('plan_movimiento', 'plan_movimiento_entrada')
    AND pm.plan_id = :plan_id
  UNION ALL
  SELECT cfe.id, cfe.event_date, cfe.amount, cfe.currency_id,
         cfe.source_type, cfe.source_id, cfe.is_income,
         inst.name || ' ' || ccn.name AS description
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
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id IS NULL), 0)    AS paid_real,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0) AS planned_amount
  FROM entries e
  LEFT JOIN cash_flow_payments p ON p.cash_flow_entry_id = e.id
  GROUP BY e.id, e.event_date, e.amount, e.currency_id,
           e.source_type, e.source_id, e.is_income, e.description
),
open_debt_monthly AS (
  SELECT
    cfe.id,
    MIN(COALESCE(p.planned_date, p.created_at::date))             AS event_date,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0) AS amount,
    cfe.currency_id,
    cfe.source_type,
    cfe.source_id,
    cfe.is_income,
    o.description,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id IS NULL), 0)    AS paid_real,
    COALESCE(SUM(p.amount) FILTER (WHERE p.plan_id = :plan_id), 0) AS planned_amount
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
  u.planned_amount * COALESCE(cr.value, 1) AS planned_amount_converted
FROM unified u
LEFT JOIN currency_rates cr
  ON cr.currency_id = u.currency_id
  AND cr.rate_date  = COALESCE(u.event_date, CURRENT_DATE)
ORDER BY u.event_date ASC NULLS LAST
"""
)


def _entry_fields(r) -> dict:
    return dict(
        id=r["id"],
        amount=r["amount"],
        paid_real=r["paid_real"],
        planned_amount=r["planned_amount"],
        currency_id=r["currency_id"],
        source_type=r["source_type"],
        source_id=r["source_id"],
        description=r["description"],
        amount_converted=r["amount_converted"],
        paid_real_converted=r["paid_real_converted"],
        planned_amount_converted=r["planned_amount_converted"],
    )


def get_timeline(db: Session, user: User, plan_id: uuid.UUID | None) -> TimelineOut:
    if plan_id is None:
        raise AppError(ErrorCode.plan_id_required)
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise AppError(ErrorCode.not_found)

    rows = db.execute(_TIMELINE_SQL, {"user_id": user.id, "plan_id": plan_id}).mappings().all()

    open_debts: list[TimelineEntryOut] = []
    buckets: dict[str, dict] = {}  # "YYYY-MM" -> {"incomes": [], "expenses": [], "ti": Decimal, "te": Decimal}

    for r in rows:
        if r["event_date"] is None:
            open_debts.append(TimelineEntryOut(**_entry_fields(r)))
            continue
        key = r["event_date"].strftime("%Y-%m")
        b = buckets.setdefault(key, {"incomes": [], "expenses": [], "ti": Decimal("0"), "te": Decimal("0")})
        entry = MonthEntryOut(event_date=r["event_date"], **_entry_fields(r))
        if r["is_income"]:
            b["incomes"].append(entry)
            b["ti"] += r["amount_converted"]
        else:
            b["expenses"].append(entry)
            b["te"] += r["amount_converted"]

    months: list[MonthOut] = []
    for key in sorted(buckets):
        b = buckets[key]
        b["incomes"].sort(key=lambda e: (e.event_date, str(e.id)))
        b["expenses"].sort(key=lambda e: (e.event_date, str(e.id)))
        months.append(
            MonthOut(
                month=key,
                total_income=b["ti"],
                total_expenses=b["te"],
                balance=b["ti"] - b["te"],
                incomes=b["incomes"],
                expenses=b["expenses"],
            )
        )

    return TimelineOut(months=months, open_debts=open_debts)
```

- [ ] **Step 3: Router** `app/routers/cash_flow_entries.py`:

```python
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.cash_flow_entry import TimelineOut
from app.services import cash_flow_entry_service as svc

router = APIRouter(tags=["cash-flow-entries"])


@router.get("/cash-flow-entries", response_model=TimelineOut)
def get_timeline(
    plan_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TimelineOut:
    return svc.get_timeline(db, user, plan_id)
```

- [ ] **Step 4: Registrar el router** en `app/main.py` (import + include):

```python
from app.routers import cash_flow_entries
```
```python
app.include_router(cash_flow_entries.router)
```

- [ ] **Step 5: Test base + helpers** `tests/test_get_cash_flow_entries.py`. Helpers de fuentes baratas
  (tarjeta para egresos, plan_movement para ingresos) sobre `seed_cc_refs` (Peso id 1, Institution id 1,
  Network id 1). **Si algún modelo exige columnas NOT NULL no provistas acá, completalas leyendo el modelo**
  (mismo criterio que el slice de pagos).

```python
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.credit_card import CreditCard
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    return db_session.execute(select(User).order_by(User.created_at.desc())).scalars().first()


def _plan(db_session, user, *, is_default=False):
    plan = Plan(
        user_id=user.id, name="Plan", is_default=is_default, is_engine_generated=False,
        selected_at=datetime.now(timezone.utc), dial_amount=Decimal("0"), dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _card(db_session, user, *, deleted_at=None):
    card = CreditCard(
        user_id=user.id, institution_id=1, card_network_id=1, current_limit=Decimal("100000.00"),
        closing_day=13, due_day=25, financing_rate_local=Decimal("10.00"), overdue_rate_local=Decimal("12.00"),
        financing_rate_usd=Decimal("5.00"), overdue_rate_usd=Decimal("6.00"), rates_add_vat=False,
        review_findings="[]", is_ready=True, deleted_at=deleted_at,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def _entry(db_session, user, *, source_type, source_id, event_date, is_income=False, amount="6000.00", currency_id=1):
    e = CashFlowEntry(
        user_id=user.id, event_date=event_date, is_income=is_income, amount=Decimal(amount),
        currency_id=currency_id, source_type=source_type, source_id=source_id,
    )
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    return e


def _card_entry(db_session, user, **kw):
    card = _card(db_session, user)
    return _entry(db_session, user, source_type="tarjeta_credito", source_id=card.id, **kw)


def _income_entry(db_session, user, plan, *, event_date, amount="45000.00"):
    pm = PlanMovement(
        plan_id=plan.id, kind="ingreso", currency_id=1, principal_amount=Decimal(amount),
        start_date=date(2026, 1, 1), rates_add_vat=False,
    )
    db_session.add(pm)
    db_session.commit()
    db_session.refresh(pm)
    return _entry(
        db_session, user, source_type="plan_movimiento_entrada", source_id=pm.id,
        event_date=event_date, is_income=True, amount=amount,
    )


def _pay(db_session, entry, *, amount, plan_id=None, planned_date=None):
    p = CashFlowPayment(
        cash_flow_entry_id=entry.id, amount=Decimal(amount), plan_id=plan_id, planned_date=planned_date
    )
    db_session.add(p)
    db_session.commit()
    return p


def test_timeline_groups_by_month_and_flow(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00")     # egreso junio
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 5), amount="45000.00")  # ingreso junio
    r = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert [m["month"] for m in body["months"]] == ["2026-06"]
    jun = body["months"][0]
    assert jun["total_income"] == "45000.00"
    assert jun["total_expenses"] == "6000.00"
    assert jun["balance"] == "39000.00"
    assert len(jun["incomes"]) == 1 and len(jun["expenses"]) == 1
    assert "is_income" not in jun["incomes"][0]  # no se serializa
    assert body["open_debts"] == []
```

- [ ] **Step 6: Run → rojo, luego verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q
```

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/schemas/cash_flow_entry.py app/services/cash_flow_entry_service.py app/routers/cash_flow_entries.py app/main.py tests/test_get_cash_flow_entries.py && git commit -m "feat: GET /cash-flow-entries (timeline base)"
```

---

## Task 2: Tests — validaciones + pagos derivados + plan entries

**Files:** Modify `tests/test_get_cash_flow_entries.py` (agregar tests; reusar helpers de Task 1).

- [ ] **Step 1: Agregar los tests**:

```python
def test_requires_plan_id(client, db_session, seed_cc_refs):
    headers = _headers(client)
    assert client.get("/cash-flow-entries", headers=headers).json()["code"] == "plan_id_required"


def test_plan_not_owned(client, db_session, seed_cc_refs):
    headers_a = _headers(client, email="a@b.com")
    user_a = _last_user(db_session)
    plan_a = _plan(db_session, user_a)
    headers_b = _headers(client, email="b@b.com")
    assert client.get(f"/cash-flow-entries?plan_id={plan_a.id}", headers=headers_b).status_code == 404


def test_plan_not_found(client, db_session, seed_cc_refs):
    headers = _headers(client)
    assert client.get(f"/cash-flow-entries?plan_id={uuid.uuid4()}", headers=headers).status_code == 404


def test_empty_timeline(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    assert client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json() == {"months": [], "open_debts": []}


def test_paid_real_and_planned_amount(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    entry = _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00")
    _pay(db_session, entry, amount="2000.00")  # real
    _pay(db_session, entry, amount="1000.00", plan_id=plan.id, planned_date=date(2026, 6, 10))  # planificado de este plan
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert e["paid_real"] == "2000.00"
    assert e["planned_amount"] == "1000.00"


def test_planned_of_other_plan_excluded(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    other = _plan(db_session, user)
    entry = _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00")
    _pay(db_session, entry, amount="999.00", plan_id=other.id, planned_date=date(2026, 6, 10))
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert e["planned_amount"] == "0.00"


def test_plan_entry_only_for_its_plan(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    other = _plan(db_session, user)
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 5))  # entry del plan
    # pedido con OTRO plan: la entry de plan no aparece
    body = client.get(f"/cash-flow-entries?plan_id={other.id}", headers=headers).json()
    assert body == {"months": [], "open_debts": []}
    # pedido con SU plan: aparece
    body2 = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()
    assert len(body2["months"][0]["incomes"]) == 1
```

- [ ] **Step 2: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add tests/test_get_cash_flow_entries.py && git commit -m "test: GET cash-flow-entries validaciones + pagos derivados"
```

---

## Task 3: Tests — deuda_abierta (madre en open_debts + proyección mensual)

**Files:** Modify `tests/test_get_cash_flow_entries.py`.

> Requiere una `obligations` con `source_type` de la entry `deuda_abierta`. La obligación tiene varias columnas
> NOT NULL y FKs a catálogos (`obligation_types`, `priority_levels`). Crear la obligación y los catálogos
> mínimos **leyendo el modelo `Obligation` y los seeds existentes** (mirar cómo lo hacen los tests de
> `debt_service` / `test_*debt*`), o insertando filas mínimas directas. El helper de abajo asume un helper
> `_open_debt(db_session, user)` que devuelve la `Obligation` (kind deuda_abierta) ya insertada.

- [ ] **Step 1: Helper `_open_debt` + tests**. Implementar `_open_debt` insertando una `Obligation` válida
  (deuda_abierta) — completar los NOT NULL/FK según el modelo y los catálogos sembrados. Luego:

```python
def test_open_debt_madre_in_open_debts(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    debt = _open_debt(db_session, user)
    _entry(db_session, user, source_type="deuda_abierta", source_id=debt.id, event_date=None, amount="30000.00")
    body = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()
    assert body["months"] == []
    assert len(body["open_debts"]) == 1
    od = body["open_debts"][0]
    assert od["amount"] == "30000.00"
    assert "event_date" not in od  # las de open_debts no traen event_date


def test_open_debt_projected_into_month(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    debt = _open_debt(db_session, user)
    entry = _entry(db_session, user, source_type="deuda_abierta", source_id=debt.id, event_date=None, amount="30000.00")
    _pay(db_session, entry, amount="5000.00", plan_id=plan.id, planned_date=date(2026, 7, 15))  # planificado julio
    body = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()
    # madre sigue en open_debts; además una proyección en julio (expenses), mismo id, amount = planificado del mes
    assert len(body["open_debts"]) == 1
    jul = next(m for m in body["months"] if m["month"] == "2026-07")
    proj = jul["expenses"][0]
    assert proj["id"] == str(entry.id)
    assert proj["amount"] == "5000.00"
    assert jul["total_expenses"] == "5000.00"
```

- [ ] **Step 2: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add tests/test_get_cash_flow_entries.py && git commit -m "test: GET cash-flow-entries proyección de deuda_abierta"
```

---

## Task 4: Tests — description por fuente + soft-deleted + conversión + orden

**Files:** Modify `tests/test_get_cash_flow_entries.py`.

- [ ] **Step 1: Tests**:

```python
def test_description_credit_card_and_soft_deleted_included(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user, deleted_at=datetime.now(timezone.utc))  # soft-deleted
    _entry(db_session, user, source_type="tarjeta_credito", source_id=card.id, event_date=date(2026, 6, 10), amount="100.00")
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert e["description"] == "Scotiabank Amex"  # emisor + red (rama 4 no filtra deleted_at)


def test_conversion_x1_without_rate(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="6000.00", currency_id=1)
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert e["amount"] == "6000.00"
    assert e["amount_converted"] == "6000.00"  # Peso no cotiza -> COALESCE(...,1)


def test_conversion_scaled_with_rate(client, db_session, seed_cc_refs):
    # moneda no legal (Dólar) con una cotización en la fecha de la entry
    from app.models.currency import Currency
    from app.models.currency_rate import CurrencyRate
    db_session.add(Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True))
    db_session.commit()
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    db_session.add(CurrencyRate(currency_id=3, rate_date=date(2026, 6, 10), value=Decimal("40.000000")))
    db_session.commit()
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="10.00", currency_id=3)
    e = client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"][0]["expenses"][0]
    assert Decimal(e["amount_converted"]) == Decimal("400.000000")  # 10 × 40


def test_months_ordered(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    _card_entry(db_session, user, event_date=date(2026, 8, 1), amount="1.00")
    _card_entry(db_session, user, event_date=date(2026, 6, 1), amount="2.00")
    _card_entry(db_session, user, event_date=date(2026, 7, 1), amount="3.00")
    months = [m["month"] for m in client.get(f"/cash-flow-entries?plan_id={plan.id}", headers=headers).json()["months"]]
    assert months == ["2026-06", "2026-07", "2026-08"]
```

> Nota conversión: `Currency`/`CurrencyRate` — completar columnas según el modelo si faltara alguna NOT NULL.
> `value` Numeric(14,6); el producto conserva escala (por eso el assert compara `Decimal`, no string exacto).

- [ ] **Step 2: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add tests/test_get_cash_flow_entries.py && git commit -m "test: GET cash-flow-entries description/soft-deleted/conversión/orden"
```

---

## Task 5: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (476 previos + los nuevos del timeline).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/get-cash-flow-entries` a `main` (1 commit). Push **manual**.

> Notion: el GET ya está documentado en `Endpoints → Flujo de dinero → GET cash-flow-entries` y se implementó
> tal cual; no requiere actualización.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** schemas (Task 1), query `text()` con las 4 ramas + pagos + open_debt_monthly +
  conversión + armado (Task 1), validaciones + pagos derivados + plan entries (Task 2), deuda_abierta madre y
  proyección (Task 3), description por fuente + tarjeta soft-deleted incluida + conversión ×1/escalada + orden
  (Task 4). Reusa `plan_id_required`/`not_found` (sin codes nuevos). ✓
- **Placeholder scan:** sin TBD/TODO ni código roto. Un único helper (`_open_debt`) se describe para que el
  implementer lo complete leyendo el modelo `Obligation` + catálogos (mismo patrón usado y resuelto en el slice
  de pagos para NOT NULL); su contrato (devuelve una `Obligation` deuda_abierta) está explícito. ✓
- **Consistencia de tipos:** `TimelineEntryOut` (open_debts) vs `MonthEntryOut` (con `event_date`); `get_timeline`
  firma usada por el router; SQL devuelve exactamente las columnas que `_entry_fields` lee. ✓
- **Riesgo conocido:** columnas NOT NULL en helpers de fuentes (`Plan`, `PlanMovement`, `CreditCard`,
  `Obligation`, `Currency`, `CurrencyRate`) — el implementer ajusta los kwargs leyendo cada modelo si algo
  falla al insertar (proven en el slice de pagos). El `_entry` de `CashFlowEntry` ya cubre sus NOT NULL.
