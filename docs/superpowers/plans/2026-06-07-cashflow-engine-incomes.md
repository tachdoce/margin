# Slice 2 — `CashFlowEngine.incomes` (motor de materialización) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear el motor que materializa las `cash_flow_entries` de un income (más la función canónica de fechado de la familia), sin cablearlo a los endpoints todavía.

**Architecture:** Paquete nuevo `app/services/cash_flow/`. `date_utils.compute_event_date` resuelve la fecha real de un evento (clamp de fin de mes + corrimiento de finde opcional). `incomes.materialize_income(db, income_id, *, today, horizon)` arma el conjunto de entries objetivo del income y lo reconcilia por UPSERT contra la clave lógica `(año, mes, currency_id)`; no hace commit (lo controla el caller). `today`/`horizon` son parámetros con default para tests deterministas.

**Tech Stack:** SQLAlchemy 2.0, pytest, Python 3.13 (`backend/.venv`). Postgres `margin_test` (los tests usan `create_all`, sin migración).

**Spec:** `docs/superpowers/specs/2026-06-07-cashflow-engine-incomes-design.md`.

**Git:** rama `feat/cashflow-engine-incomes`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/services/cash_flow/
├── __init__.py        # paquete (vacío)                                  (NUEVO)
├── date_utils.py      # compute_event_date                               (NUEVO)
└── incomes.py         # materialize_income                               (NUEVO)
backend/tests/
├── test_cash_flow_date_utils.py      # compute_event_date (puro)         (NUEVO)
└── test_cashflow_engine_incomes.py   # materialize_income (con DB)       (NUEVO)
```

---

## Task 1: `compute_event_date` (TDD)

**Files:**
- Create: `backend/app/services/cash_flow/__init__.py`
- Create: `backend/app/services/cash_flow/date_utils.py`
- Create: `backend/tests/test_cash_flow_date_utils.py`

- [ ] **Step 1: Crear la rama**

```bash
cd /Users/tachone/proyectos/margin
git checkout -b feat/cashflow-engine-incomes
```

- [ ] **Step 2: Escribir el test que falla en `backend/tests/test_cash_flow_date_utils.py`**

```python
from datetime import date

from app.services.cash_flow.date_utils import compute_event_date


def test_clamp_fin_de_mes_febrero():
    # día 31 en febrero no bisiesto -> 28
    assert compute_event_date(2026, 2, 31, False) == date(2026, 2, 28)


def test_clamp_fin_de_mes_bisiesto():
    # día 31 en febrero bisiesto -> 29
    assert compute_event_date(2024, 2, 31, False) == date(2024, 2, 29)


def test_shift_sabado_a_lunes():
    # 2026-08-15 es sábado -> lunes 2026-08-17
    assert date(2026, 8, 15).weekday() == 5
    assert compute_event_date(2026, 8, 15, True) == date(2026, 8, 17)


def test_shift_domingo_a_lunes():
    # 2026-08-16 es domingo -> lunes 2026-08-17
    assert date(2026, 8, 16).weekday() == 6
    assert compute_event_date(2026, 8, 16, True) == date(2026, 8, 17)


def test_shift_lunes_cruza_mes_a_viernes_anterior():
    # 2025-05-31 es sábado; el lunes siguiente (2025-06-02) cruza de mes -> viernes anterior 2025-05-30
    assert date(2025, 5, 31).weekday() == 5
    assert compute_event_date(2025, 5, 31, True) == date(2025, 5, 30)


def test_sin_shift_queda_literal():
    # sábado sin shift_weekends queda en su día (solo aplica el clamp)
    assert compute_event_date(2026, 8, 15, False) == date(2026, 8, 15)
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_flow_date_utils.py -v`
Expected: FALLA en la colección con `ModuleNotFoundError: No module named 'app.services.cash_flow'`.

- [ ] **Step 4: Crear el paquete `backend/app/services/cash_flow/__init__.py`** (archivo vacío)

```python
```

- [ ] **Step 5: Crear `backend/app/services/cash_flow/date_utils.py`**

```python
import calendar
from datetime import date, timedelta


def compute_event_date(year: int, month: int, target_day: int, shift_weekends: bool) -> date:
    """Fecha real de un evento del cronograma. Canónica de la familia CashFlowEngine.

    1. Clamp de fin de mes: si target_day excede los días del mes, usa el último día.
    2. Corrimiento de finde (solo si shift_weekends): si cae sábado/domingo, corre al lunes
       siguiente; si ese lunes cruza de mes, al viernes anterior. Nunca sale del mes objetivo.
    """
    last_day = calendar.monthrange(year, month)[1]
    day = min(target_day, last_day)
    result = date(year, month, day)

    if shift_weekends and result.weekday() >= 5:  # 5 = sábado, 6 = domingo
        monday = result + timedelta(days=7 - result.weekday())  # sáb->+2, dom->+1
        if monday.month == month:
            result = monday
        else:
            # el lunes cruzó de mes -> viernes anterior (sáb->-1, dom->-2)
            result = result - timedelta(days=result.weekday() - 4)

    return result
```

- [ ] **Step 6: Correr el test y verificar que pasa**

Run: `pytest tests/test_cash_flow_date_utils.py -v`
Expected: PASAN los 6 tests.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/cash_flow/__init__.py backend/app/services/cash_flow/date_utils.py backend/tests/test_cash_flow_date_utils.py
git commit -m "feat(backend): compute_event_date (fechado canónico CashFlowEngine)"
```

---

## Task 2: `materialize_income` (TDD)

**Files:**
- Create: `backend/app/services/cash_flow/incomes.py`
- Create: `backend/tests/test_cashflow_engine_incomes.py`

- [ ] **Step 1: Escribir el test que falla en `backend/tests/test_cashflow_engine_incomes.py`**

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.currency import Currency
from app.models.income import Income
from app.models.income_type import IncomeType
from app.models.user import User
from app.services.cash_flow.incomes import materialize_income


def _seed_income(db_session, **over):
    """country UY (seed_uy) + currency + income_type + user + un income recurrente por default."""
    db_session.add(Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True))
    db_session.add(IncomeType(id=1, code="sueldo", name="Sueldo", visible=True))
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    fields = dict(
        user_id=user.id,
        income_type_id=1,
        currency_id=1,
        amount=Decimal("45000.00"),
        description="Sueldo principal",
        is_monthly_recurring=True,
        payment_day=5,
        first_income_date=None,
        total_months=None,
        shift_weekends=False,
    )
    fields.update(over)
    income = Income(**fields)
    db_session.add(income)
    db_session.flush()
    return income


def _entries(db_session, income):
    return list(
        db_session.execute(
            select(CashFlowEntry)
            .where(CashFlowEntry.source_type == "ingreso", CashFlowEntry.source_id == income.id)
            .order_by(CashFlowEntry.event_date)
        ).scalars()
    )


def test_recurrente_genera_una_por_mes(db_session, seed_uy):
    income = _seed_income(db_session)
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 6  # jul..dic
    for e in entries:
        assert e.is_income is True
        assert e.source_type == "ingreso"
        assert e.source_id == income.id
        assert e.amount == Decimal("45000.00")
        assert e.currency_id == 1
        assert e.event_date.day == 5
    assert entries[0].event_date == date(2026, 7, 5)
    assert entries[-1].event_date == date(2026, 12, 5)


def test_mes_actual_se_salta_si_el_dia_ya_paso(db_session, seed_uy):
    income = _seed_income(db_session, payment_day=5)
    # hoy 2026-07-10: el 5 de julio ya pasó -> julio no se materializa
    materialize_income(db_session, income.id, today=date(2026, 7, 10), horizon=date(2026, 12, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 5  # ago..dic
    assert entries[0].event_date == date(2026, 8, 5)


def test_duracion_fija_genera_total_months(db_session, seed_uy):
    income = _seed_income(
        db_session,
        is_monthly_recurring=False,
        payment_day=None,
        first_income_date=date(2026, 8, 10),
        total_months=3,
    )
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 3  # ago, sep, oct
    assert [e.event_date for e in entries] == [date(2026, 8, 10), date(2026, 9, 10), date(2026, 10, 10)]


def test_cobro_unico(db_session, seed_uy):
    income = _seed_income(
        db_session,
        is_monthly_recurring=False,
        payment_day=None,
        first_income_date=date(2026, 8, 10),
        total_months=1,
    )
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 10)


def test_soft_deleted_borra_futuras_sin_pago(db_session, seed_uy):
    income = _seed_income(db_session)
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))
    assert len(_entries(db_session, income)) == 6

    income.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    assert len(_entries(db_session, income)) == 0


def test_idempotencia(db_session, seed_uy):
    income = _seed_income(db_session)
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    assert len(_entries(db_session, income)) == 6  # no duplica


def test_cambio_amount_actualiza_sin_duplicar(db_session, seed_uy):
    income = _seed_income(db_session)
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    income.amount = Decimal("50000.00")
    db_session.flush()
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 6
    assert all(e.amount == Decimal("50000.00") for e in entries)


def test_cambio_payment_day_mueve_in_place(db_session, seed_uy):
    income = _seed_income(db_session, payment_day=5)
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 9, 30))
    before = _entries(db_session, income)
    assert [e.event_date.day for e in before] == [5, 5, 5]  # jul, ago, sep
    ids_before = {e.id for e in before}

    income.payment_day = 20
    db_session.flush()
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2026, 9, 30))

    after = _entries(db_session, income)
    assert len(after) == 3
    assert [e.event_date.day for e in after] == [20, 20, 20]
    assert {e.id for e in after} == ids_before  # misma fila, movida in place


def test_achicar_total_months_conserva_la_que_tiene_pago_real(db_session, seed_uy):
    income = _seed_income(
        db_session,
        is_monthly_recurring=False,
        payment_day=None,
        first_income_date=date(2026, 8, 10),
        total_months=4,  # ago, sep, oct, nov
    )
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))
    entries = _entries(db_session, income)
    assert len(entries) == 4
    nov = entries[-1]
    assert nov.event_date == date(2026, 11, 10)
    # un pago real imputado a la entry de noviembre
    db_session.add(CashFlowPayment(cash_flow_entry_id=nov.id, amount=Decimal("45000.00")))
    db_session.flush()

    income.total_months = 2  # ago, sep
    db_session.flush()
    materialize_income(db_session, income.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    after = _entries(db_session, income)
    dates = [e.event_date for e in after]
    # ago y sep (objetivo) + nov (sobrevive por tener pago real); oct se borró
    assert date(2026, 8, 10) in dates
    assert date(2026, 9, 10) in dates
    assert date(2026, 11, 10) in dates
    assert date(2026, 10, 10) not in dates
    assert len(after) == 3


def test_shift_weekends_produce_dia_habil(db_session, seed_uy):
    # 2026-08-15 es sábado; con shift_weekends corre al lunes 2026-08-17
    income = _seed_income(db_session, payment_day=15, shift_weekends=True)
    materialize_income(db_session, income.id, today=date(2026, 8, 1), horizon=date(2026, 8, 31))

    entries = _entries(db_session, income)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 17)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_cashflow_engine_incomes.py -v`
Expected: FALLA en la colección con `ModuleNotFoundError: No module named 'app.services.cash_flow.incomes'`.

- [ ] **Step 3: Crear `backend/app/services/cash_flow/incomes.py`**

```python
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.income import Income
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


def _target_event_dates(income: Income, today: date, horizon: date) -> list[date]:
    """event_date de cada entry que el income debería tener. Vacío si está borrado."""
    if income.deleted_at is not None:
        return []

    dates: list[date] = []
    if income.is_monthly_recurring:
        for y, m in _iter_months(today.year, today.month, horizon.year, horizon.month):
            ed = compute_event_date(y, m, income.payment_day, income.shift_weekends)
            if today <= ed <= horizon:
                dates.append(ed)
    else:
        y, m = income.first_income_date.year, income.first_income_date.month
        day = income.first_income_date.day
        for _ in range(income.total_months):
            ed = compute_event_date(y, m, day, income.shift_weekends)
            if today <= ed <= horizon:
                dates.append(ed)
            m += 1
            if m > 12:
                m, y = 1, y + 1
    return dates


def materialize_income(
    db: Session, income_id: uuid.UUID, *, today: date | None = None, horizon: date = HORIZON
) -> None:
    """(Re)materializa las cash_flow_entries de un income por UPSERT contra su clave lógica
    (año, mes, currency_id). No hace commit: la transacción la controla el caller."""
    if today is None:
        today = date.today()

    income = db.execute(
        select(Income).where(Income.id == income_id).with_for_update()
    ).scalar_one_or_none()
    if income is None:
        return

    targets = _target_event_dates(income, today, horizon)

    existing = list(
        db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "ingreso",
                CashFlowEntry.source_id == income.id,
            )
        ).scalars()
    )
    by_key = {(e.event_date.year, e.event_date.month, e.currency_id): e for e in existing}

    target_keys: set[tuple[int, int, int]] = set()
    for ed in targets:
        key = (ed.year, ed.month, income.currency_id)
        target_keys.add(key)
        entry = by_key.get(key)
        if entry is not None:
            entry.amount = income.amount
            entry.event_date = ed
        else:
            db.add(
                CashFlowEntry(
                    user_id=income.user_id,
                    event_date=ed,
                    is_income=True,
                    amount=income.amount,
                    currency_id=income.currency_id,
                    source_type="ingreso",
                    source_id=income.id,
                )
            )

    # borrar las existentes fuera del objetivo: solo futuras (event_date >= today) sin pago real
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
            if e.event_date is not None and e.event_date >= today and e.id not in paid_ids:
                db.delete(e)

    db.flush()
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/test_cashflow_engine_incomes.py -v`
Expected: PASAN los 10 tests.

- [ ] **Step 5: Regresión de la suite completa**

Run: `pytest -q`
Expected: pasan todos.

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/cash_flow/incomes.py backend/tests/test_cashflow_engine_incomes.py
git commit -m "feat(backend): CashFlowEngine.incomes (materialize_income)"
```

---

## Notas de cierre

- Al terminar: existe `app/services/cash_flow/` con `compute_event_date` y `materialize_income`, testeados. Nadie lo invoca todavía (el cableado a los endpoints es el slice 3).
- **Cierre:** squash-merge de `feat/cashflow-engine-incomes` → un commit `feat: CashFlowEngine.incomes` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** `compute_event_date` clamp + finde + canónica (§2) — Task 1 Steps 5 + tests Step 2 ✓; firma y lock `FOR UPDATE` + no-op si no existe + sin commit (§3.1) — Task 2 Step 3 ✓; conjunto objetivo recurrente/duración-fija/soft-deleted (§3.2) — `_target_event_dates` ✓; reconciliación UPSERT por clave `(año, mes, currency_id)` + borrado acotado a futuras sin pago real (§3.3) — Task 2 Step 3 ✓; `today`/`horizon` inyectables (§4) — firma con defaults ✓; todos los casos de test de §5 (recurrente, mes actual saltado, duración fija, cobro único, soft-deleted, idempotencia, cambio amount, cambio payment_day in-place, achicar total_months conservando pago real, shift_weekends) — Task 2 Step 1 ✓.
- **Placeholders:** ninguno; código completo en cada step (incl. `__init__.py` vacío explícito).
- **Consistencia de tipos:** `materialize_income(db, income_id, *, today=None, horizon=HORIZON)` idéntica entre spec, implementación (Task 2 Step 3) y llamadas de test (Task 2 Step 1). La clave lógica `(año, mes, currency_id)` y `source_type='ingreso'` coinciden en implementación y aserciones. `compute_event_date(year, month, target_day, shift_weekends)` idéntica entre Task 1 y su uso en Task 2. Las fechas de finde de los tests (`2026-08-15` sáb, `2026-08-16` dom, `2025-05-31` sáb fin de mes) están verificadas contra el calendario real.
```
