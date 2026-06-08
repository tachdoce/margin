# `CashFlowEngine.plan_movements` (motor) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear el motor `materialize_plan_movement` que materializa las `cash_flow_entries` de un `plan_movements` según su `kind`, sin cablearlo a endpoints.

**Architecture:** `app/services/cash_flow/plan_movements.py` con `materialize_plan_movement(db, movement_id, *, today, horizon)`, que reusa `compute_event_date`. Arma el conjunto de entries objetivo según el `kind` (`ingreso`/`deuda_informal`/`prestamo`) y lo reconcilia por UPSERT contra la clave lógica `(source_type, año, mes, currency_id)`. No valida (confía en la fila) ni hace commit (lo controla el caller).

**Tech Stack:** SQLAlchemy 2.0, pytest, Python 3.13 (`backend/.venv`). Tests con `create_all`.

**Spec:** `docs/superpowers/specs/2026-06-07-cashflow-engine-plan-movements-design.md`.

**Git:** rama `feat/cashflow-engine-plan-movements`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/services/cash_flow/plan_movements.py        # materialize_plan_movement   (NUEVO)
backend/tests/test_cashflow_engine_plan_movements.py    # tests del motor             (NUEVO)
```

---

## Task 1: `materialize_plan_movement` (TDD)

**Files:**
- Create: `backend/app/services/cash_flow/plan_movements.py`
- Create: `backend/tests/test_cashflow_engine_plan_movements.py`

- [ ] **Step 1: Crear la rama**

```bash
cd /Users/tachone/proyectos/margin
git checkout -b feat/cashflow-engine-plan-movements
```

- [ ] **Step 2: Escribir el test que falla en `backend/tests/test_cashflow_engine_plan_movements.py`**

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.currency import Currency
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.services.cash_flow.plan_movements import materialize_plan_movement


def _seed_movement(db_session, **over):
    """country UY (seed_uy, vat 22) + currency + user + plan no-default + un plan_movement."""
    db_session.add(Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True))
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    plan = Plan(
        user_id=user.id,
        name="Escenario",
        is_default=False,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("0.00"),
        dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.flush()
    fields = dict(
        plan_id=plan.id,
        kind="ingreso",
        currency_id=1,
        description=None,
        principal_amount=Decimal("45000.00"),
        start_date=date(2026, 7, 5),
        income_duration_months=None,
        installment_amount=None,
        installment_start_date=None,
        total_installments=None,
        financing_rate=None,
        overdue_rate=None,
        rates_add_vat=True,
    )
    fields.update(over)
    mov = PlanMovement(**fields)
    db_session.add(mov)
    db_session.flush()
    return mov


def _entries(db_session, mov):
    return list(
        db_session.execute(
            select(CashFlowEntry)
            .where(
                CashFlowEntry.source_id == mov.id,
                CashFlowEntry.source_type.in_(("plan_movimiento", "plan_movimiento_entrada")),
            )
            .order_by(CashFlowEntry.event_date, CashFlowEntry.source_type)
        ).scalars()
    )


def test_ingreso_unico(db_session, seed_uy):
    mov = _seed_movement(db_session, kind="ingreso", income_duration_months=1, start_date=date(2026, 8, 10))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, mov)
    assert len(entries) == 1
    e = entries[0]
    assert e.event_date == date(2026, 8, 10)
    assert e.is_income is True
    assert e.source_type == "plan_movimiento"
    assert e.amount == Decimal("45000.00")
    assert e.financing_rate is None and e.overdue_rate is None


def test_ingreso_limitado(db_session, seed_uy):
    mov = _seed_movement(db_session, kind="ingreso", income_duration_months=3, start_date=date(2026, 8, 10))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, mov)
    assert [e.event_date for e in entries] == [date(2026, 8, 10), date(2026, 9, 10), date(2026, 10, 10)]


def test_ingreso_recurrente(db_session, seed_uy):
    mov = _seed_movement(db_session, kind="ingreso", income_duration_months=None, start_date=date(2026, 7, 5))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    entries = _entries(db_session, mov)
    assert len(entries) == 6  # jul..dic
    assert all(e.is_income is True and e.source_type == "plan_movimiento" for e in entries)


def test_deuda_informal(db_session, seed_uy):
    mov = _seed_movement(
        db_session, kind="deuda_informal", principal_amount=Decimal("30000.00"), start_date=date(2026, 8, 10)
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, mov)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 10)
    assert entries[0].is_income is False
    assert entries[0].source_type == "plan_movimiento"


def test_prestamo_entrada_y_cuotas(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 8, 1),
        total_installments=3,
        financing_rate=None,
        overdue_rate=None,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    entries = _entries(db_session, mov)
    entradas = [e for e in entries if e.source_type == "plan_movimiento_entrada"]
    cuotas = [e for e in entries if e.source_type == "plan_movimiento"]
    assert len(entradas) == 1
    assert entradas[0].is_income is True
    assert entradas[0].event_date == date(2026, 7, 1)
    assert entradas[0].amount == Decimal("200000.00")
    assert len(cuotas) == 3
    assert all(c.is_income is False and c.amount == Decimal("10500.00") for c in cuotas)
    assert [c.event_date for c in cuotas] == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]


def test_convivencia_entrada_y_primera_cuota_mismo_mes(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 7, 1),  # mismo mes que start_date
        total_installments=2,
        financing_rate=None,
        overdue_rate=None,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    julio = [e for e in _entries(db_session, mov) if e.event_date.month == 7 and e.event_date.year == 2026]
    assert len(julio) == 2
    assert {e.source_type for e in julio} == {"plan_movimiento", "plan_movimiento_entrada"}


def test_tasa_efectiva_con_iva(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 8, 1),
        total_installments=1,
        financing_rate=Decimal("72.00"),
        overdue_rate=Decimal("85.00"),
        rates_add_vat=True,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    cuota = [e for e in _entries(db_session, mov) if e.source_type == "plan_movimiento"][0]
    assert cuota.financing_rate == Decimal("87.84")  # 72.00 * 1.22
    assert cuota.overdue_rate == Decimal("103.70")  # 85.00 * 1.22


def test_tasa_sin_iva_queda_literal(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 8, 1),
        total_installments=1,
        financing_rate=Decimal("72.00"),
        overdue_rate=None,
        rates_add_vat=False,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    cuota = [e for e in _entries(db_session, mov) if e.source_type == "plan_movimiento"][0]
    assert cuota.financing_rate == Decimal("72.00")
    assert cuota.overdue_rate is None


def test_cuota_corre_por_finde(db_session, seed_uy):
    # 2026-08-15 es sábado; la cuota (vencimiento) corre al lunes 2026-08-17
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 8, 15),
        total_installments=1,
        financing_rate=None,
        overdue_rate=None,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    cuota = [e for e in _entries(db_session, mov) if e.source_type == "plan_movimiento"][0]
    assert cuota.event_date == date(2026, 8, 17)


def test_ingreso_no_corre_por_finde(db_session, seed_uy):
    # 2026-08-15 es sábado; el ingreso NO corre (queda literal)
    mov = _seed_movement(
        db_session, kind="ingreso", income_duration_months=None, start_date=date(2026, 8, 15)
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 8, 1), horizon=date(2026, 8, 31))

    entries = _entries(db_session, mov)
    assert len(entries) == 1
    assert entries[0].event_date == date(2026, 8, 15)


def test_no_modela_el_pasado(db_session, seed_uy):
    mov = _seed_movement(db_session, kind="ingreso", income_duration_months=1, start_date=date(2026, 1, 10))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    assert _entries(db_session, mov) == []


def test_idempotencia(db_session, seed_uy):
    mov = _seed_movement(db_session, kind="ingreso", income_duration_months=None, start_date=date(2026, 7, 5))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2026, 12, 31))

    assert len(_entries(db_session, mov)) == 6


def test_reconciliacion_achicar_cuotas(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="prestamo",
        principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1),
        income_duration_months=1,
        installment_amount=Decimal("10500.00"),
        installment_start_date=date(2026, 8, 1),
        total_installments=4,
        financing_rate=None,
        overdue_rate=None,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))
    cuotas = [e for e in _entries(db_session, mov) if e.source_type == "plan_movimiento"]
    assert len(cuotas) == 4

    mov.total_installments = 2
    db_session.flush()
    materialize_plan_movement(db_session, mov.id, today=date(2026, 6, 1), horizon=date(2027, 12, 31))

    cuotas = [e for e in _entries(db_session, mov) if e.source_type == "plan_movimiento"]
    assert [c.event_date for c in cuotas] == [date(2026, 8, 1), date(2026, 9, 1)]
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_engine_plan_movements.py -v`
Expected: FALLA en la colección con `ModuleNotFoundError: No module named 'app.services.cash_flow.plan_movements'`.

- [ ] **Step 4: Crear `backend/app/services/cash_flow/plan_movements.py`**

```python
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.country import Country
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.services.cash_flow.date_utils import compute_event_date

HORIZON = date(2027, 12, 31)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _monthly_dates(start: date, count: int | None, horizon: date, *, shift: bool):
    """event_date de cada mes desde `start`, durante `count` meses (None = hasta el horizonte)."""
    y, m, day = start.year, start.month, start.day
    i = 0
    while (count is None or i < count) and (y, m) <= (horizon.year, horizon.month):
        yield compute_event_date(y, m, day, shift)
        y, m = _next_month(y, m)
        i += 1


def _effective_rate(rate: Decimal | None, rates_add_vat: bool, vat_rate: Decimal) -> Decimal | None:
    if rate is None:
        return None
    if rates_add_vat:
        rate = rate * (Decimal(1) + vat_rate / Decimal(100))
    return rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _target(source_type, event_date, is_income, amount, financing_rate=None, overdue_rate=None):
    return {
        "source_type": source_type,
        "event_date": event_date,
        "is_income": is_income,
        "amount": amount,
        "financing_rate": financing_rate,
        "overdue_rate": overdue_rate,
    }


def _target_entries(db: Session, movement: PlanMovement, user: User, today: date, horizon: date) -> list[dict]:
    targets: list[dict] = []
    kind = movement.kind

    if kind == "ingreso":
        if movement.income_duration_months == 1:
            ed = movement.start_date  # única: fecha literal exacta
            if today <= ed <= horizon:
                targets.append(_target("plan_movimiento", ed, True, movement.principal_amount))
        else:
            for ed in _monthly_dates(movement.start_date, movement.income_duration_months, horizon, shift=False):
                if today <= ed <= horizon:
                    targets.append(_target("plan_movimiento", ed, True, movement.principal_amount))

    elif kind == "deuda_informal":
        ed = movement.start_date  # literal exacta
        if today <= ed <= horizon:
            targets.append(_target("plan_movimiento", ed, False, movement.principal_amount))

    elif kind == "prestamo":
        # entrada de plata (1 fila, literal)
        ed = movement.start_date
        if today <= ed <= horizon:
            targets.append(_target("plan_movimiento_entrada", ed, True, movement.principal_amount))
        # cuotas (N filas, corren por finde, con tasa efectiva)
        vat_rate = db.get(Country, user.country_code).vat_rate
        fin = _effective_rate(movement.financing_rate, movement.rates_add_vat, vat_rate)
        over = _effective_rate(movement.overdue_rate, movement.rates_add_vat, vat_rate)
        for ed in _monthly_dates(movement.installment_start_date, movement.total_installments, horizon, shift=True):
            if today <= ed <= horizon:
                targets.append(
                    _target("plan_movimiento", ed, False, movement.installment_amount, fin, over)
                )

    return targets


def materialize_plan_movement(
    db: Session, movement_id: uuid.UUID, *, today: date | None = None, horizon: date = HORIZON
) -> None:
    """(Re)materializa las cash_flow_entries de un plan_movements por UPSERT contra su clave lógica
    (source_type, año, mes, currency_id). No valida (confía en la fila) ni hace commit (lo controla el caller)."""
    if today is None:
        today = date.today()

    movement = db.execute(
        select(PlanMovement).where(PlanMovement.id == movement_id).with_for_update()
    ).scalar_one_or_none()
    if movement is None:
        return

    plan = db.get(Plan, movement.plan_id)
    user = db.get(User, plan.user_id)

    targets = _target_entries(db, movement, user, today, horizon)

    existing = list(
        db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_id == movement.id,
                CashFlowEntry.source_type.in_(("plan_movimiento", "plan_movimiento_entrada")),
            )
        ).scalars()
    )
    by_key = {(e.source_type, e.event_date.year, e.event_date.month, e.currency_id): e for e in existing}

    target_keys: set[tuple] = set()
    for t in targets:
        key = (t["source_type"], t["event_date"].year, t["event_date"].month, movement.currency_id)
        target_keys.add(key)
        entry = by_key.get(key)
        if entry is not None:
            entry.amount = t["amount"]
            entry.event_date = t["event_date"]
            entry.financing_rate = t["financing_rate"]
            entry.overdue_rate = t["overdue_rate"]
        else:
            db.add(
                CashFlowEntry(
                    user_id=plan.user_id,
                    event_date=t["event_date"],
                    is_income=t["is_income"],
                    amount=t["amount"],
                    currency_id=movement.currency_id,
                    financing_rate=t["financing_rate"],
                    overdue_rate=t["overdue_rate"],
                    source_type=t["source_type"],
                    source_id=movement.id,
                )
            )

    # borrar las existentes fuera del objetivo, solo futuras (las entries de plan no tienen pagos reales)
    for key, e in by_key.items():
        if key not in target_keys and e.event_date is not None and e.event_date >= today:
            db.delete(e)

    db.flush()
```

- [ ] **Step 5: Correr el test y verificar que pasa**

Run: `pytest tests/test_cashflow_engine_plan_movements.py -v`
Expected: PASAN los 13 tests.

- [ ] **Step 6: Regresión de la suite completa**

Run: `pytest -q`
Expected: pasan todos.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/cash_flow/plan_movements.py backend/tests/test_cashflow_engine_plan_movements.py
git commit -m "feat(backend): CashFlowEngine.plan_movements (materialize_plan_movement)"
```

---

## Notas de cierre

- Al terminar: existe `materialize_plan_movement`, testeado por kind. Nadie lo invoca todavía (los endpoints de `plan_movements` son un slice posterior).
- **Cierre:** squash-merge de `feat/cashflow-engine-plan-movements` → un commit `feat: CashFlowEngine.plan_movements` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** firma + lock + user_id vía plan + no-commit + no-validación (§2) — Step 4 ✓; conjunto objetivo por kind ingreso/deuda_informal/prestamo con fechado correcto (§3) — `_target_entries` ✓; tasa efectiva con/sin IVA/NULL (§4) — `_effective_rate` + tests ✓; reconciliación por clave `(source_type, año, mes, currency_id)` + borrado solo futuras (§5) — Step 4 + test reconciliación ✓; today/horizon inyectables (§2) — firma ✓; todos los casos de test de §7 (kinds, convivencia, IVA, finde cuota vs ingreso, no-pasado, idempotencia, reconciliación) — Step 2 ✓.
- **Placeholders:** ninguno; código completo.
- **Consistencia de tipos:** `materialize_plan_movement(db, movement_id, *, today=None, horizon=HORIZON)` igual en spec/impl/tests; clave lógica con `source_type` consistente; `compute_event_date(year, month, target_day, shift_weekends)` usado con `shift=False` (ingreso) y `shift=True` (cuotas); `Country` PK = `code` (db.get con `user.country_code`); `vat_rate` Numeric(4,2); fechas de finde verificadas (2026-08-15 sábado → 2026-08-17 lunes). Tasa efectiva: 72.00×1.22=87.84, 85.00×1.22=103.70.
```
