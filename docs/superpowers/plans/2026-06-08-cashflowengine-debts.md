# CashFlowEngine.debts (motor) — Plan de implementación

> **For agentic workers:** Ejecutar según el modo que elija el usuario (inline o subagente con higiene de
> comandos: `cd` no `git -C`, sin `2>&1`). TDD: test → rojo → implementación → verde → commit por task.

**Goal:** Crear `materialize_debt` — materializa `cash_flow_entries` desde `obligations` de kind `deuda`
(cronograma de cuotas y pago único), congelando tasas efectivas. Solo el motor; sin endpoints.

**Architecture:** Espeja `materialize_expense` (gate `is_ready`, UPSERT por clave lógica `(source_type=
'deuda', source_id, año, mes, currency_id)`, borrado de stale futuras sin pago real con raise, pasado
intacto, `today`/`horizon` inyectables, `flush` sin commit). Agrega: objetivo por cronograma de cuotas,
tasas efectivas congeladas (helper `_effective_rate` replicado de `plan_movements`), y raise si falta
`due_day` en cronograma.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, pytest. Spec:
`docs/superpowers/specs/2026-06-08-cashflowengine-debts-design.md`.

**Rama:** `feat/cashflow-debts` → squash-merge a `main`.

---

## Task 0: Crear la rama

- [ ] **Step 1:**

```bash
git checkout -b feat/cashflow-debts
```

---

## Task 1: Motor `materialize_debt` + tests

**Files:**
- Create: `backend/app/services/cash_flow/debts.py`
- Test: `backend/tests/test_cashflow_debts.py`

- [ ] **Step 1: Escribir los tests (rojo)**

`backend/tests/test_cashflow_debts.py`:

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
from app.services.cash_flow.debts import materialize_debt

TODAY = date(2026, 6, 1)
HORIZON = date(2026, 12, 31)


@pytest.fixture
def user(db_session, seed_uy_currency):
    # seed_uy (vía seed_uy_currency) crea UY con vat_rate 22.00
    db_session.add(PriorityLevel(level=4, name="Prioritaria", description="x"))
    db_session.flush()
    db_session.add(
        ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                       description="x", default_priority_level=4, visible=True)
    )
    db_session.flush()
    u = User(country_code="UY")
    db_session.add(u)
    db_session.flush()
    return u


def _deuda(db_session, user, **overrides):
    kwargs = dict(
        user_id=user.id,
        obligation_type_id=10,
        priority_level=4,
        currency_id=1,
        amount=Decimal("5000.00"),
        is_monthly_recurring=False,
        due_day=10,
        first_due_date=date(2026, 7, 1),
        total_installments=12,
        financing_rate=Decimal("55.00"),
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
            select(CashFlowEntry)
            .where(CashFlowEntry.source_type == "deuda", CashFlowEntry.source_id == obligation_id)
            .order_by(CashFlowEntry.event_date)
        ).scalars()
    )


def test_cronograma_materializa_cuotas(db_session, user):
    o = _deuda(db_session, user)  # first_due 2026-07-01, due_day 10, 12 cuotas
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    # cuotas con venc en jul..dic 2026 (las de 2027 caen fuera del horizonte) → 6
    assert len(entries) == 6
    for e in entries:
        assert e.is_income is False
        assert e.source_type == "deuda"
        assert e.amount == Decimal("5000.00")
        assert e.currency_id == 1
        assert e.event_date.day == 10
    assert entries[0].event_date == date(2026, 7, 10)
    assert entries[-1].event_date == date(2026, 12, 10)


def test_tasas_efectivas_con_vat(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("55.00"), overdue_rate=None, rates_add_vat=True)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    for e in _entries(db_session, o.id):
        assert e.financing_rate == Decimal("67.10")  # 55 × 1.22
        assert e.overdue_rate is None


def test_tasas_sin_vat(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("55.00"), rates_add_vat=False)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    for e in _entries(db_session, o.id):
        assert e.financing_rate == Decimal("55.00")


def test_pago_unico_una_fila(db_session, user):
    o = _deuda(db_session, user, total_installments=None, due_day=None,
               first_due_date=date(2026, 8, 15))
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 15)


def test_gate_not_ready_no_materializa(db_session, user):
    o = _deuda(db_session, user, is_ready=False)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_is_closed_borra_futuras(db_session, user):
    o = _deuda(db_session, user)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert len(_entries(db_session, o.id)) == 6
    o.is_closed = True
    db_session.flush()
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_acortar_cronograma_reconcilia(db_session, user):
    o = _deuda(db_session, user)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert len(_entries(db_session, o.id)) == 6
    o.total_installments = 3  # solo jul, ago, sep 2026
    db_session.flush()
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 3
    assert entries[-1].event_date == date(2026, 9, 10)


def test_cambio_tasas_reescribe_futuras(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("55.00"), rates_add_vat=True)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert all(e.financing_rate == Decimal("67.10") for e in _entries(db_session, o.id))
    o.financing_rate = Decimal("100.00")
    db_session.flush()
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert all(e.financing_rate == Decimal("122.00") for e in _entries(db_session, o.id))  # 100 × 1.22


def test_pago_real_stale_lanza_excepcion(db_session, user):
    o = _deuda(db_session, user)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    fut = _entries(db_session, o.id)[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=fut.id, amount=Decimal("5000.00")))  # real
    db_session.flush()
    o.is_closed = True
    db_session.flush()
    with pytest.raises(RuntimeError):
        materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)


def test_pago_planificado_stale_se_borra(db_session, user):
    o = _deuda(db_session, user)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
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
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    assert _entries(db_session, o.id) == []


def test_pasado_no_se_toca(db_session, user):
    o = _deuda(db_session, user)
    past = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 3, 10), is_income=False,
        amount=Decimal("5000.00"), currency_id=1, source_type="deuda", source_id=o.id,
        financing_rate=Decimal("40.00"),
    )
    db_session.add(past)
    db_session.flush()
    past_id = past.id
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    survivors = {e.id: e for e in _entries(db_session, o.id)}
    assert past_id in survivors
    assert survivors[past_id].financing_rate == Decimal("40.00")  # no se reescribió


def test_due_day_null_en_cronograma_lanza_excepcion(db_session, user):
    o = _deuda(db_session, user, due_day=None, total_installments=12)
    with pytest.raises(RuntimeError):
        materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)


def test_shift_weekends_corre_finde(db_session, user):
    # 2026-07-04 es sábado; con shift → lunes 2026-07-06
    o = _deuda(db_session, user, due_day=4, total_installments=1,
               first_due_date=date(2026, 7, 1), shift_weekends=True)
    materialize_debt(db_session, o.id, today=TODAY, horizon=HORIZON)
    entries = _entries(db_session, o.id)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 7, 6)
```

- [ ] **Step 2: Correr los tests, verificar que fallan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_debts.py -q
```
Esperado: FAIL (ModuleNotFoundError: app.services.cash_flow.debts).

- [ ] **Step 3: Implementar el motor**

`backend/app/services/cash_flow/debts.py`:

```python
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.country import Country
from app.models.obligation import Obligation
from app.models.user import User
from app.services.cash_flow.date_utils import compute_event_date

HORIZON = date(2027, 12, 31)


def _effective_rate(rate: Decimal | None, rates_add_vat: bool, vat_rate: Decimal | None) -> Decimal | None:
    if rate is None:
        return None
    if rates_add_vat:
        rate = rate * (Decimal(1) + vat_rate / Decimal(100))
    return rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _target_event_dates(obligation: Obligation, today: date, horizon: date) -> list[date]:
    """event_date de cada cuota/evento que la deuda debería tener. Vacío si está cerrada."""
    if obligation.is_closed:
        return []

    dates: list[date] = []
    if obligation.total_installments is not None:  # cronograma de cuotas
        if obligation.due_day is None:
            raise RuntimeError(
                f"materialize_debt: deuda con cronograma {obligation.id} sin due_day"
            )
        fdd = obligation.first_due_date
        y, m = fdd.year, fdd.month
        for _ in range(obligation.total_installments):
            ed = compute_event_date(y, m, obligation.due_day, obligation.shift_weekends)
            if today <= ed <= horizon:
                dates.append(ed)
            m += 1
            if m > 12:
                m, y = 1, y + 1
    else:  # pago único
        fdd = obligation.first_due_date
        ed = compute_event_date(fdd.year, fdd.month, fdd.day, obligation.shift_weekends)
        if today <= ed <= horizon:
            dates.append(ed)
    return dates


def materialize_debt(
    db: Session, obligation_id: uuid.UUID, *, today: date | None = None, horizon: date = HORIZON
) -> None:
    """(Re)materializa las cash_flow_entries de una obligación-deuda por UPSERT contra su clave lógica
    (año, mes, currency_id), congelando las tasas efectivas. Gate: is_ready False → no-op. No commit."""
    if today is None:
        today = date.today()

    obligation = db.execute(
        select(Obligation).where(Obligation.id == obligation_id).with_for_update()
    ).scalar_one_or_none()
    if obligation is None:
        return
    if not obligation.is_ready:
        return  # gate: no-op silencioso

    targets = _target_event_dates(obligation, today, horizon)

    # tasas efectivas (iguales para todas las filas): una sola vez
    if obligation.financing_rate is not None or obligation.overdue_rate is not None:
        user = db.get(User, obligation.user_id)
        vat_rate = db.get(Country, user.country_code).vat_rate
    else:
        vat_rate = None
    fin_eff = _effective_rate(obligation.financing_rate, obligation.rates_add_vat, vat_rate)
    over_eff = _effective_rate(obligation.overdue_rate, obligation.rates_add_vat, vat_rate)

    existing = list(
        db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "deuda",
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
            entry.financing_rate = fin_eff
            entry.overdue_rate = over_eff
        else:
            db.add(
                CashFlowEntry(
                    user_id=obligation.user_id,
                    event_date=ed,
                    is_income=False,
                    amount=obligation.amount,
                    currency_id=obligation.currency_id,
                    financing_rate=fin_eff,
                    overdue_rate=over_eff,
                    source_type="deuda",
                    source_id=obligation.id,
                )
            )

    # borrar stale: solo futuras (event_date >= today) sin pago real; con pago real → raise.
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
                        f"materialize_debt: invariante violado, "
                        f"entry {e.id} con pago real quedó fuera del objetivo"
                    )
                db.delete(e)

    db.flush()
```

- [ ] **Step 4: Correr los tests, verificar que pasan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_debts.py -q
```
Esperado: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cash_flow/debts.py backend/tests/test_cashflow_debts.py
git commit -m "feat: CashFlowEngine.debts (motor)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Suite completa

- [ ] **Step 1:**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```
Esperado: PASS (todo verde, +13 nuevos).

---

## Cierre

Tras Task 2 verde: **finishing-a-development-branch** → squash-merge `feat/cashflow-debts` a `main` → push
(manual/prompteado).
