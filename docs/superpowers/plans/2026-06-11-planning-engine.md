# PlanningEngine v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Motor que, dado un plan, decide qué pagar de cada egreso mes a mes (obligatorios → mínimos → avalancha por tasa con look-ahead 2·X) y materializa la decisión como `cash_flow_payments` auto-generados.

**Architecture:** Paquete nuevo `app/services/planning/` con una simulación forward que espeja la matemática de `get_timeline` (capacidad, prorrateo, arrastre de tarjetas). Endpoint `POST /plans/{plan_id}/planning` → 204; el front refresca el timeline. Prerrequisito: la cascada del timeline pasa a priorizar el pago planificado sobre el real.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Postgres, pytest. Spec: `docs/superpowers/specs/2026-06-11-planning-engine-design.md`.

**Convenciones:** plata siempre `Decimal`; servicios lanzan `AppError`, nunca `HTTPException`; correr comandos desde `backend/` con `.venv/bin/pytest`. Rama de trabajo: `feat/planning-engine` (ya existe, tiene el spec).

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `backend/app/services/cash_flow_entry_service.py` (modificar, líneas ~195-200) | Cascada: prioridad planificado > real |
| `backend/app/services/planning/__init__.py` (crear) | Exporta `run_planning` |
| `backend/app/services/planning/engine.py` (crear) | Carga, simulación, materialización |
| `backend/app/routers/plans.py` (modificar) | `POST /plans/{plan_id}/planning` → 204 |
| `backend/tests/test_get_cash_flow_entries.py` (modificar) | Test del cambio de cascada |
| `backend/tests/test_planning.py` (crear) | Tests del motor |

---

### Task 1: Cascada del timeline — el planificado domina sobre el real (spec §8.1)

**Files:**
- Modify: `backend/app/services/cash_flow_entry_service.py:195-200`
- Test: `backend/tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Test que falla**

Agregar al final de `backend/tests/test_get_cash_flow_entries.py` (usa los helpers `_headers`, `_last_user`, `_plan`, `_card`, `_pay` ya definidos en el archivo):

```python
def test_carryover_planned_overrides_paid_real(client, db_session, seed_cc_refs):
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
    _pay(db_session, prev, amount="200.00")  # pago real parcial
    _pay(db_session, prev, amount="1000.00", plan_id=plan.id, planned_date=date(2026, 5, 29))  # plan: total
    db_session.add(CashFlowEntry(
        user_id=user.id, event_date=date(2026, 6, 29), is_income=False, amount=Decimal("0.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("0.00"),
    ))
    db_session.commit()
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = next(m for m in out.months if m.month == "2026-06")
    # el planificado (total) domina sobre el real parcial -> sin arrastre -> row en 0 oculta
    assert jun.expenses == []
```

- [ ] **Step 2: Verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_get_cash_flow_entries.py::test_carryover_planned_overrides_paid_real -v`
Expected: FAIL — con la prioridad actual el pago usado es el real (200), arrastra 810.80 y junio tiene una row.

- [ ] **Step 3: Invertir la prioridad en la cascada**

En `backend/app/services/cash_flow_entry_service.py`, dentro del loop de series de tarjeta, reemplazar:

```python
            if r["paid_real"] > 0:
                payment = r["paid_real"]
            elif r["planned_amount"] > 0:
                payment = r["planned_amount"]
```

por:

```python
            # el planificado es la intención total del mes; el real es su ejecución parcial
            if r["planned_amount"] > 0:
                payment = r["planned_amount"]
            elif r["paid_real"] > 0:
                payment = r["paid_real"]
```

- [ ] **Step 4: Verificar que pasa, y que el resto del archivo no se rompió**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_get_cash_flow_entries.py -v`
Expected: PASS todos. Si algún test de carryover existente falla, es porque codificaba la prioridad vieja con real y planificado en la misma entry: revisar contra el spec §8.1 y actualizar su expectativa (el planificado domina). Los tests `test_carryover_*` actuales no mezclan ambos en la misma entry, así que no deberían tocar.

- [ ] **Step 5: Commit**

```bash
git add tests/test_get_cash_flow_entries.py app/services/cash_flow_entry_service.py
git commit -m "fix(timeline): el pago planificado domina sobre el real en la cascada"
```

---

### Task 2: Paquete planning + endpoint (esqueleto)

**Files:**
- Create: `backend/app/services/planning/__init__.py`
- Create: `backend/app/services/planning/engine.py`
- Modify: `backend/app/routers/plans.py`
- Test: `backend/tests/test_planning.py`

- [ ] **Step 1: Tests que fallan**

Crear `backend/tests/test_planning.py`:

```python
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import AppError, ErrorCode
from app.models.cash_balance import CashBalance
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan
from app.models.user import User
from app.models.user_financial_settings import UserFinancialSettings
from app.services.planning import run_planning

TODAY = date(2026, 6, 15)


def _user(db_session):
    u = User(country_code="UY")
    db_session.add(u)
    db_session.flush()
    return u


def _plan(db_session, user, dial="0"):
    p = Plan(
        user_id=user.id, name="Plan", is_default=False, is_engine_generated=False,
        selected_at=datetime.now(timezone.utc), dial_amount=Decimal(dial), dial_currency_id=1,
    )
    db_session.add(p)
    db_session.flush()
    return p


def _cash(db_session, user, amount, currency_id=1):
    db_session.add(CashBalance(user_id=user.id, currency_id=currency_id, amount=Decimal(amount)))
    db_session.flush()


def _need(db_session, user, amount):
    db_session.add(UserFinancialSettings(user_id=user.id, monthly_need_amount=Decimal(amount)))
    db_session.flush()


def _entry(db_session, user, *, event_date, amount, source_type="gasto", is_income=False,
           currency_id=1, fin=None, over=None, minimum=None, source_id=None):
    e = CashFlowEntry(
        user_id=user.id, event_date=event_date, is_income=is_income, amount=Decimal(amount),
        currency_id=currency_id,
        financing_rate=None if fin is None else Decimal(fin),
        overdue_rate=None if over is None else Decimal(over),
        minimum_payment=None if minimum is None else Decimal(minimum),
        source_type=source_type, source_id=source_id or uuid.uuid4(),
    )
    db_session.add(e)
    db_session.flush()
    return e


def _pay(db_session, entry, amount, *, plan_id=None, planned_date=None, auto=False):
    p = CashFlowPayment(
        cash_flow_entry_id=entry.id, amount=Decimal(amount), plan_id=plan_id,
        planned_date=planned_date, is_auto_generated=auto,
    )
    db_session.add(p)
    db_session.flush()
    return p


def _autos(db_session, plan):
    return list(db_session.execute(
        select(CashFlowPayment)
        .where(CashFlowPayment.plan_id == plan.id, CashFlowPayment.is_auto_generated.is_(True))
        .order_by(CashFlowPayment.planned_date)
    ).scalars())


def _auto_for(db_session, plan, entry):
    return [a for a in _autos(db_session, plan) if a.cash_flow_entry_id == entry.id]


# --- esqueleto ---

def test_plan_not_found(db_session, seed_uy_currency):
    user = _user(db_session)
    with pytest.raises(AppError) as exc:
        run_planning(db_session, user, uuid.uuid4(), today=TODAY)
    assert exc.value.code == ErrorCode.not_found


def test_plan_of_other_user(db_session, seed_uy_currency):
    user = _user(db_session)
    other = _user(db_session)
    plan = _plan(db_session, other)
    with pytest.raises(AppError) as exc:
        run_planning(db_session, user, plan.id, today=TODAY)
    assert exc.value.code == ErrorCode.not_found


def test_empty_run_ok(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    run_planning(db_session, user, plan.id, today=TODAY)
    assert _autos(db_session, plan) == []


def test_endpoint_204_and_404(client, db_session, seed_uy_currency):
    token = client.post("/auth/register", json={"email": "p@x.com", "password": "12345678"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    user = db_session.execute(select(User)).scalars().all()[-1]
    plan = _plan(db_session, user)
    assert client.post(f"/plans/{plan.id}/planning", headers=headers).status_code == 204
    assert client.post(f"/plans/{uuid.uuid4()}/planning", headers=headers).status_code == 404
```

- [ ] **Step 2: Verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.planning'`.

- [ ] **Step 3: Esqueleto del motor**

Crear `backend/app/services/planning/__init__.py`:

```python
from app.services.planning.engine import run_planning

__all__ = ["run_planning"]
```

Crear `backend/app/services/planning/engine.py`:

```python
"""PlanningEngine: decide qué pagar de cada egreso dentro de un plan.

Simula mes a mes (espejo de la matemática de get_timeline), asigna por prioridad
(obligatorios -> mínimos -> avalancha por tasa con look-ahead) y materializa la decisión
como cash_flow_payments con is_auto_generated=true.
Spec: docs/superpowers/specs/2026-06-11-planning-engine-design.md
"""
import uuid
from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan
from app.models.user import User


def run_planning(db: Session, user: User, plan_id: uuid.UUID, *, today: date | None = None) -> None:
    today = today or date.today()
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise AppError(ErrorCode.not_found)

    db.execute(
        delete(CashFlowPayment).where(
            CashFlowPayment.plan_id == plan.id,
            CashFlowPayment.is_auto_generated.is_(True),
        )
    )
    db.flush()
    db.commit()
```

Agregar al final de `backend/app/routers/plans.py` (y sumar el import `from app.services import planning` junto a los imports existentes):

```python
@router.post("/plans/{plan_id}/planning", status_code=status.HTTP_204_NO_CONTENT)
def run_planning(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    planning.run_planning(db, user, plan_id)
```

- [ ] **Step 4: Verificar que pasa**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/planning/ app/routers/plans.py tests/test_planning.py
git commit -m "feat: esqueleto del PlanningEngine + POST /plans/{id}/planning"
```

---

### Task 3: Loader + asignación de obligatorios y mínimos + materialización

**Files:**
- Modify: `backend/app/services/planning/engine.py` (reemplazo completo)
- Test: `backend/tests/test_planning.py`

- [ ] **Step 1: Tests que fallan**

Agregar a `backend/tests/test_planning.py` (los imports de `PlanMovement` van arriba con el resto):

```python
from app.models.plan_movement import PlanMovement


# --- población y exclusiones (el truco observable: un egreso con pago real parcial
# y decisión de pago total genera fila auto; si está excluido, no genera nada) ---

def test_gasto_incluido_con_real_parcial_genera_cap(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "10000")
    _need(db_session, user, "0")
    e = _entry(db_session, user, event_date=date(2026, 6, 20), amount="1000.00")
    _pay(db_session, e, "300.00")  # real parcial
    run_planning(db_session, user, plan.id, today=TODAY)
    autos = _autos(db_session, plan)
    assert len(autos) == 1
    assert autos[0].cash_flow_entry_id == e.id
    assert autos[0].amount == Decimal("1000.00")  # decisión total explícita (spec §8)
    assert autos[0].planned_date == date(2026, 6, 20)
    assert autos[0].is_auto_generated is True


def test_deuda_abierta_y_mes_pasado_excluidos(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "10000")
    _need(db_session, user, "0")
    abierta = _entry(db_session, user, event_date=None, amount="1000.00", source_type="deuda_abierta")
    pasada = _entry(db_session, user, event_date=date(2026, 5, 20), amount="1000.00")
    _pay(db_session, abierta, "300.00")
    _pay(db_session, pasada, "300.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    assert _autos(db_session, plan) == []


def test_plan_movement_de_otro_plan_excluido(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    otro = _plan(db_session, user)
    _cash(db_session, user, "10000")
    _need(db_session, user, "0")

    def _pm(p):
        pm = PlanMovement(
            plan_id=p.id, kind="deuda_informal", currency_id=1, principal_amount=Decimal("1000.00"),
            start_date=date(2026, 6, 20), rates_add_vat=False,
        )
        db_session.add(pm)
        db_session.flush()
        return pm

    mio = _entry(db_session, user, event_date=date(2026, 6, 20), amount="1000.00",
                 source_type="plan_movimiento", source_id=_pm(plan).id)
    ajeno = _entry(db_session, user, event_date=date(2026, 6, 20), amount="1000.00",
                   source_type="plan_movimiento", source_id=_pm(otro).id)
    _pay(db_session, mio, "300.00")
    _pay(db_session, ajeno, "300.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    autos = _autos(db_session, plan)
    assert [a.cash_flow_entry_id for a in autos] == [mio.id]


# --- pasos 1 y 2 ---

def test_minimos_se_pagan_aunque_quede_negativo(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="3000.00")  # gasto obligatorio
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="2000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="300.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    autos = _autos(db_session, plan)
    # gasto: pago total asumido, sin fila. Tarjeta: queda en el mínimo -> fila (capacity 0, sin paso 3)
    assert len(autos) == 1
    assert autos[0].cash_flow_entry_id == card.id
    assert autos[0].amount == Decimal("300.00")


def test_deuda_con_tasas_min_total_sin_fila(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="1000.00",
           source_type="deuda", fin="90.00", over="120.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # deuda con tasas: mínimo = total -> decidido == total sin pagos reales -> sin fila
    assert _autos(db_session, plan) == []


def test_manual_es_piso_y_no_genera_fila(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="1000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    _pay(db_session, card, "400.00", plan_id=plan.id, planned_date=date(2026, 6, 22))
    run_planning(db_session, user, plan.id, today=TODAY)
    # manual 400 cubre el mínimo y es la decisión exacta -> sin fila auto
    assert _autos(db_session, plan) == []
```

- [ ] **Step 2: Verificar que fallan**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: FAIL los 6 tests nuevos (los autos no se crean / se crean de más). Los 4 de Task 2 siguen PASS.

- [ ] **Step 3: Implementación**

Reemplazar **completo** `backend/app/services/planning/engine.py` por:

```python
"""PlanningEngine: decide qué pagar de cada egreso dentro de un plan.

Simula mes a mes (espejo de la matemática de get_timeline), asigna por prioridad
(obligatorios -> mínimos -> avalancha por tasa con look-ahead) y materializa la decisión
como cash_flow_payments con is_auto_generated=true.
Spec: docs/superpowers/specs/2026-06-11-planning-engine-design.md
"""
import calendar
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.models.user_financial_settings import UserFinancialSettings
from app.services.cash_flow.constants import PROJECTED_MINIMUM_RATE

# misma conversión y mismo ancla de efectivo que el timeline
from app.services.cash_flow_entry_service import _available_now, _rate

Q = Decimal("0.01")
ZERO = Decimal("0")
_PLAN_TYPES = ("plan_movimiento", "plan_movimiento_entrada")


@dataclass
class _Entry:
    id: uuid.UUID
    event_date: date
    is_income: bool
    source_type: str
    source_id: uuid.UUID
    currency_id: int
    base_amount: Decimal
    financing_rate: Decimal
    overdue_rate: Decimal
    minimum_payment: Decimal | None  # solo tarjetas (en el resto viene None)
    paid_real: Decimal
    manual: Decimal
    fx: Decimal
    carry_in: Decimal = ZERO   # arrastre del propio motor (tarjetas)
    decided: Decimal = ZERO    # decisión del motor (pago total del mes)

    @property
    def month(self) -> tuple[int, int]:
        return (self.event_date.year, self.event_date.month)

    @property
    def amount(self) -> Decimal:
        """Monto efectivo: base + arrastre."""
        return self.base_amount + self.carry_in

    @property
    def has_rates(self) -> bool:
        return self.financing_rate > 0 or self.overdue_rate > 0

    @property
    def is_card(self) -> bool:
        return self.source_type == "tarjeta_credito"

    @property
    def minimum(self) -> Decimal:
        """Tarjeta con arrastre: 15% del efectivo (regla del timeline); tarjeta sin
        arrastre: el de la entry; deudas/plan_movements con tasas: el total."""
        if self.is_card:
            if self.carry_in > 0:
                return (self.amount * PROJECTED_MINIMUM_RATE).quantize(Q, rounding=ROUND_HALF_UP)
            return self.minimum_payment if self.minimum_payment is not None else self.amount
        return self.amount

    @property
    def committed(self) -> Decimal:
        """Compromiso previo: manual si > 0, si no real (espejo de _effective_planned)."""
        if self.manual > 0:
            return self.manual
        return self.paid_real

    @property
    def saldo(self) -> Decimal:
        return self.amount - self.decided

    def consumption(self) -> Decimal:
        """Plata que falta salir del efectivo por esta entry, convertida."""
        return max(ZERO, self.decided - self.paid_real) * self.fx


def _payment_sums(db: Session, entry_ids: list[uuid.UUID], plan: Plan) -> tuple[dict, dict]:
    if not entry_ids:
        return {}, {}
    paid = dict(
        db.execute(
            select(CashFlowPayment.cash_flow_entry_id, func.sum(CashFlowPayment.amount))
            .where(CashFlowPayment.cash_flow_entry_id.in_(entry_ids), CashFlowPayment.plan_id.is_(None))
            .group_by(CashFlowPayment.cash_flow_entry_id)
        ).all()
    )
    manual = dict(
        db.execute(
            select(CashFlowPayment.cash_flow_entry_id, func.sum(CashFlowPayment.amount))
            .where(
                CashFlowPayment.cash_flow_entry_id.in_(entry_ids),
                CashFlowPayment.plan_id == plan.id,
                CashFlowPayment.is_auto_generated.is_(False),
            )
            .group_by(CashFlowPayment.cash_flow_entry_id)
        ).all()
    )
    return paid, manual


def _load_entries(db: Session, user: User, plan: Plan, month_start: date) -> list[_Entry]:
    pm_ids = select(PlanMovement.id).where(PlanMovement.plan_id == plan.id)
    rows = list(
        db.execute(
            select(CashFlowEntry)
            .where(
                CashFlowEntry.user_id == user.id,
                CashFlowEntry.event_date.is_not(None),
                CashFlowEntry.event_date >= month_start,
                CashFlowEntry.source_type != "deuda_abierta",
                or_(
                    CashFlowEntry.source_type.notin_(_PLAN_TYPES),
                    CashFlowEntry.source_id.in_(pm_ids),
                ),
            )
            .order_by(CashFlowEntry.event_date.asc(), CashFlowEntry.id.asc())
        ).scalars()
    )
    paid, manual = _payment_sums(db, [r.id for r in rows], plan)
    return [
        _Entry(
            id=r.id, event_date=r.event_date, is_income=r.is_income,
            source_type=r.source_type, source_id=r.source_id, currency_id=r.currency_id,
            base_amount=r.amount,
            financing_rate=r.financing_rate or ZERO,
            overdue_rate=r.overdue_rate or ZERO,
            minimum_payment=r.minimum_payment if r.source_type == "tarjeta_credito" else None,
            paid_real=paid.get(r.id, ZERO),
            manual=manual.get(r.id, ZERO),
            fx=_rate(db, r.currency_id, r.event_date),
        )
        for r in rows
    ]


def _pending_income(entries: list[_Entry]) -> Decimal:
    total = ZERO
    for e in entries:
        if not e.is_income:
            continue
        eff = e.manual if e.manual > 0 else e.amount
        total += (eff - e.paid_real) * e.fx
    return total


def _spent(entries: list[_Entry]) -> Decimal:
    return sum((e.consumption() for e in entries if not e.is_income), ZERO)


def _allocate_month(entries: list[_Entry], capacity: Decimal) -> None:
    expenses = [e for e in entries if not e.is_income and e.amount > 0]
    for e in expenses:
        e.decided = e.committed
    # paso 1: obligatorios (sin tasas) al total, siempre
    for e in expenses:
        if not e.has_rates:
            e.decided = max(e.decided, e.amount)
    # paso 2: mínimos (deudas con tasas: el total), siempre
    for e in expenses:
        if e.has_rates:
            e.decided = max(e.decided, min(e.minimum, e.amount))


def _materialize(db: Session, plan: Plan, entries: list[_Entry]) -> None:
    for e in entries:
        if e.is_income or e.amount <= 0 or e.decided <= 0:
            continue
        # fila solo si la decisión difiere de lo que el timeline asume sin filas (spec §8)
        needs_row = e.decided != e.amount or (ZERO < e.paid_real < e.decided)
        if not needs_row:
            continue
        amount = e.decided - e.manual
        if amount <= 0:
            continue
        db.add(
            CashFlowPayment(
                cash_flow_entry_id=e.id, amount=amount, plan_id=plan.id,
                planned_date=e.event_date, is_auto_generated=True,
            )
        )


def run_planning(db: Session, user: User, plan_id: uuid.UUID, *, today: date | None = None) -> None:
    today = today or date.today()
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise AppError(ErrorCode.not_found)

    db.execute(
        delete(CashFlowPayment).where(
            CashFlowPayment.plan_id == plan.id,
            CashFlowPayment.is_auto_generated.is_(True),
        )
    )

    entries = _load_entries(db, user, plan, today.replace(day=1))
    months = sorted({e.month for e in entries})
    by_month = {m: [e for e in entries if e.month == m] for m in months}

    dial = plan.dial_amount * _rate(db, plan.dial_currency_id, today)
    settings_row = db.get(UserFinancialSettings, user.id)
    monthly_need = settings_row.monthly_need_amount if settings_row is not None else None

    prev_balance: Decimal | None = None
    for m in months:
        month_entries = by_month[m]
        if prev_balance is None:  # primer mes >= actual = ancla del efectivo (igual timeline)
            available = _available_now(db, user, today)
            if m == (today.year, today.month):
                if monthly_need is not None:
                    remaining = monthly_need
                else:
                    days = calendar.monthrange(today.year, today.month)[1]
                    remaining = (dial * Decimal(days - (today.day - 1)) / Decimal(days)).quantize(
                        Q, rounding=ROUND_HALF_UP
                    )
            else:
                remaining = dial
        else:
            available = prev_balance
            remaining = dial

        capacity = available + _pending_income(month_entries) - remaining
        _allocate_month(month_entries, capacity)
        prev_balance = capacity - _spent(month_entries)

    _materialize(db, plan, entries)
    db.flush()
    db.commit()
```

- [ ] **Step 4: Verificar que pasa**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/planning/engine.py tests/test_planning.py
git commit -m "feat(planning): loader, obligatorios y minimos, materializacion minima"
```

---

### Task 4: Paso 3 — avalancha por tasa (sin look-ahead)

**Files:**
- Modify: `backend/app/services/planning/engine.py`
- Test: `backend/tests/test_planning.py`

- [ ] **Step 1: Tests que fallan**

Agregar a `backend/tests/test_planning.py`. Para multi-moneda hacen falta el Dólar y su cotización:

```python
from app.models.currency import Currency
from app.models.currency_rate import CurrencyRate


def _seed_usd(db_session):
    db_session.add(Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False,
                            allowed_in_credit_card=True))
    db_session.add(CurrencyRate(currency_id=3, rate_date=date(2026, 6, 22), value=Decimal("41")))
    db_session.flush()


# --- paso 3: avalancha ---

def test_alcanza_todo_cero_filas(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "50000")
    _need(db_session, user, "0")
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="10000.00")  # gasto
    _entry(db_session, user, event_date=date(2026, 6, 22), amount="5000.00",
           source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="500.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # gasto total y tarjeta total sin pagos reales: el timeline ya asume pago total -> sin filas
    assert _autos(db_session, plan) == []


def test_avalancha_paga_tasa_mayor_primero_y_parcial(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "5200")
    _need(db_session, user, "0")
    cara = _entry(db_session, user, event_date=date(2026, 6, 20), amount="10000.00",
                  source_type="tarjeta_credito", fin="80.00", over="90.00", minimum="100.00")
    barata = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                    source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # capacity 5200; minimos 200; sobrante 5000 -> todo a la cara (80%)
    assert [a.amount for a in _auto_for(db_session, plan, cara)] == [Decimal("5100.00")]
    assert [a.amount for a in _auto_for(db_session, plan, barata)] == [Decimal("100.00")]


def test_capacity_usa_need_e_ingresos_pendientes(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "1000")
    _need(db_session, user, "600")
    _entry(db_session, user, event_date=date(2026, 6, 18), amount="4600.00",
           source_type="ingreso", is_income=True)
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # capacity = 1000 + 4600 - 600 = 5000 -> minimo 100 + 4900 extra
    assert [a.amount for a in _auto_for(db_session, plan, card)] == [Decimal("5000.00")]


def test_remaining_prorratea_dial_sin_settings(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user, dial="3000")
    _cash(db_session, user, "2000")
    # sin user_financial_settings -> dial prorrateado: junio 30 dias, hoy 16 -> 15 dias -> 1500
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    run_planning(db_session, user, plan.id, today=date(2026, 6, 16))
    # capacity = 2000 - 1500 = 500 -> minimo 100 + 400 extra
    assert [a.amount for a in _auto_for(db_session, plan, card)] == [Decimal("500.00")]


def test_cap_por_real_parcial_en_tarjeta(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "700")
    _need(db_session, user, "0")
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="1000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    _pay(db_session, card, "300.00")  # real parcial, cubre el minimo
    run_planning(db_session, user, plan.id, today=TODAY)
    # committed 300; sobrante 700 paga el saldo -> decidido 1000 == total con real parcial -> fila del total
    assert [a.amount for a in _auto_for(db_session, plan, card)] == [Decimal("1000.00")]


def test_multimoneda_paga_en_moneda_de_la_entry(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _seed_usd(db_session)
    _cash(db_session, user, "4000")
    _need(db_session, user, "0")
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="100.00", currency_id=3,
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="10.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # capacity 4000; minimo 10 USD consume 410; sobrante 3590 -> 3590/41 = 87.56 USD (ROUND_DOWN)
    assert [a.amount for a in _auto_for(db_session, plan, card)] == [Decimal("97.56")]
```

- [ ] **Step 2: Verificar que fallan**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: FAIL los 6 nuevos (sin paso 3 las tarjetas quedan en mínimos y `test_alcanza_todo_cero_filas` ve una fila de mínimo de más). El resto PASS.

- [ ] **Step 3: Implementar el paso 3**

En `backend/app/services/planning/engine.py`, reemplazar la función `_allocate_month` por:

```python
def _allocate_month(entries: list[_Entry], capacity: Decimal) -> None:
    expenses = [e for e in entries if not e.is_income and e.amount > 0]
    for e in expenses:
        e.decided = e.committed
    # paso 1: obligatorios (sin tasas) al total, siempre
    for e in expenses:
        if not e.has_rates:
            e.decided = max(e.decided, e.amount)
    # paso 2: mínimos (deudas con tasas: el total), siempre
    for e in expenses:
        if e.has_rates:
            e.decided = max(e.decided, min(e.minimum, e.amount))
    # paso 3: avalancha — cada peso extra ahorra tasa/12: va a la tasa mayor primero
    surplus = capacity - _spent(entries)
    if surplus <= 0:
        return
    candidates = sorted(
        (e for e in expenses if e.has_rates and e.saldo > 0),
        key=lambda e: (-e.financing_rate, e.event_date, str(e.id)),
    )
    for e in candidates:
        if surplus <= 0:
            break
        pay = min(e.saldo * e.fx, surplus)
        e.decided += (pay / e.fx).quantize(Q, rounding=ROUND_DOWN)  # nunca pasarse del sobrante
        surplus = capacity - _spent(entries)
```

- [ ] **Step 4: Verificar que pasa**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: PASS (16 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/planning/engine.py tests/test_planning.py
git commit -m "feat(planning): avalancha por tasa descendente con pago parcial"
```

---

### Task 5: Arrastre de tarjetas entre meses

**Files:**
- Modify: `backend/app/services/planning/engine.py`
- Test: `backend/tests/test_planning.py`

- [ ] **Step 1: Test que falla**

Agregar a `backend/tests/test_planning.py`:

```python
# --- arrastre ---

def test_arrastre_de_tarjeta_al_mes_siguiente(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "100")
    _need(db_session, user, "0")
    card_id = uuid.uuid4()
    jun = _entry(db_session, user, event_date=date(2026, 6, 22), amount="1000.00",
                 source_type="tarjeta_credito", fin="120.00", over="240.00", minimum="100.00",
                 source_id=card_id)
    jul = _entry(db_session, user, event_date=date(2026, 7, 22), amount="0.00",
                 source_type="tarjeta_credito", fin="120.00", over="240.00", minimum="0.00",
                 source_id=card_id)
    run_planning(db_session, user, plan.id, today=TODAY)
    # junio: paga el minimo 100 (capacity 100). saldo 900, financiacion 120% -> interes
    # 900 * (120/100)/12 * 1.35 = 121.50 -> arrastra 1021.50 a julio.
    # julio: capacity 0 -> minimo 15% de 1021.50 = 153.23 (siempre, aunque negativo)
    assert [a.amount for a in _auto_for(db_session, plan, jun)] == [Decimal("100.00")]
    assert [a.amount for a in _auto_for(db_session, plan, jul)] == [Decimal("153.23")]
    assert _auto_for(db_session, plan, jul)[0].planned_date == date(2026, 7, 22)
```

- [ ] **Step 2: Verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py::test_arrastre_de_tarjeta_al_mes_siguiente -v`
Expected: FAIL — julio queda con amount 0 (sin arrastre) y no genera fila.

- [ ] **Step 3: Implementar el arrastre**

En `backend/app/services/planning/engine.py`:

1. Sumar el import de `monthly_carry` junto al de `PROJECTED_MINIMUM_RATE`:

```python
from app.services.cash_flow.constants import PROJECTED_MINIMUM_RATE
from app.services.cash_flow.interest import monthly_carry
```

2. Agregar después de `_allocate_month`:

```python
def _carry_preview(entries: list[_Entry]) -> dict[tuple[uuid.UUID, int], Decimal]:
    """Arrastre por (tarjeta, moneda) con las decisiones tomadas hasta ahora."""
    out: dict[tuple[uuid.UUID, int], Decimal] = {}
    for e in entries:
        if e.is_income or not e.is_card or e.amount <= 0:
            continue
        payment = e.decided if e.decided > 0 else e.amount  # sin decisión: asume pago total
        c = monthly_carry(e.amount, payment, min(e.minimum, e.amount), e.financing_rate, e.overdue_rate)
        if c > 0:
            out[(e.source_id, e.currency_id)] = c
    return out


def _apply_carry(entries: list[_Entry], next_entries: list[_Entry]) -> None:
    carry = _carry_preview(entries)
    for n in next_entries:
        if n.is_card:
            cin = carry.get((n.source_id, n.currency_id))
            if cin:
                n.carry_in += cin
```

3. En `run_planning`, reemplazar el cuerpo del loop de meses desde `capacity = ...` hasta `prev_balance = ...` por:

```python
        capacity = available + _pending_income(month_entries) - remaining
        _allocate_month(month_entries, capacity)
        prev_balance = capacity - _spent(month_entries)
        idx = months.index(m)
        if idx + 1 < len(months):
            _apply_carry(month_entries, by_month[months[idx + 1]])
```

- [ ] **Step 4: Verificar que pasa**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: PASS (17 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/planning/engine.py tests/test_planning.py
git commit -m "feat(planning): arrastre de tarjetas entre meses (espejo de la cascada)"
```

---

### Task 6: Look-ahead de un mes con umbral 2·X

**Files:**
- Modify: `backend/app/services/planning/engine.py`
- Test: `backend/tests/test_planning.py`

- [ ] **Step 1: Tests que fallan**

Agregar a `backend/tests/test_planning.py`:

```python
# --- look-ahead 2X ---

def test_lookahead_retiene_para_tasa_futura_mayor_a_2x(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "5000")
    _need(db_session, user, "0")
    barata = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                    source_type="tarjeta_credito", fin="10.00", over="20.00", minimum="100.00")
    cara_jul = _entry(db_session, user, event_date=date(2026, 7, 22), amount="50000.00",
                      source_type="tarjeta_credito", fin="30.00", over="40.00", minimum="500.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # junio: sobrante 4900; candidata al 10% -> umbral 20%; julio tiene demanda al 30% (> 20)
    # sin fondear (surplus' de julio = -500) -> retiene todo: barata queda al minimo.
    assert [a.amount for a in _auto_for(db_session, plan, barata)] == [Decimal("100.00")]
    # julio: available 4900 -> minimo 500 + 4400 extra
    assert [a.amount for a in _auto_for(db_session, plan, cara_jul)] == [Decimal("4900.00")]


def test_lookahead_no_retiene_bajo_el_umbral(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "5000")
    _need(db_session, user, "0")
    actual = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                    source_type="tarjeta_credito", fin="10.00", over="20.00", minimum="100.00")
    futura = _entry(db_session, user, event_date=date(2026, 7, 22), amount="50000.00",
                    source_type="tarjeta_credito", fin="15.00", over="25.00", minimum="500.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # 15% < 2*10%: no se paga retener -> junio gasta el sobrante en la actual
    assert [a.amount for a in _auto_for(db_session, plan, actual)] == [Decimal("5000.00")]
    assert [a.amount for a in _auto_for(db_session, plan, futura)] == [Decimal("500.00")]
```

- [ ] **Step 2: Verificar que fallan**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: FAIL `test_lookahead_retiene_para_tasa_futura_mayor_a_2x` (junio gasta todo en la barata). `test_lookahead_no_retiene_bajo_el_umbral` PASS de casualidad (sin look-ahead nunca retiene) — protege contra retener de más.

- [ ] **Step 3: Implementar el look-ahead**

En `backend/app/services/planning/engine.py`:

1. Agregar después de `_carry_preview`:

```python
def _lookahead_reserve(
    entries: list[_Entry], next_entries: list[_Entry], threshold: Decimal, dial: Decimal
) -> Decimal:
    """Plata a retener en M para M+1: demanda de M+1 a tasa > threshold que su propia
    capacidad standalone no cubre. Retener cuesta un mes a la tasa actual X y rinde
    (Y - X) por mes: se recupera en un mes cuando Y >= 2X (threshold = 2X)."""
    if not next_entries:
        return ZERO
    carry = _carry_preview(entries)
    saved = [(n, n.carry_in) for n in next_entries]
    try:
        for n in next_entries:
            if n.is_card:
                n.carry_in += carry.get((n.source_id, n.currency_id), ZERO)
        surplus = _pending_income(next_entries) - dial
        demand = ZERO
        for n in next_entries:
            if n.is_income or n.amount <= 0:
                continue
            if not n.has_rates:
                surplus -= max(ZERO, n.amount - n.paid_real) * n.fx
                continue
            floor = max(n.committed, min(n.minimum, n.amount))
            surplus -= max(ZERO, floor - n.paid_real) * n.fx
            if n.financing_rate > threshold:
                demand += max(ZERO, n.amount - floor) * n.fx
        return max(ZERO, demand - max(ZERO, surplus))
    finally:
        for n, cin in saved:
            n.carry_in = cin
```

2. Cambiar la firma de `_allocate_month` y el loop del paso 3:

```python
def _allocate_month(
    entries: list[_Entry], capacity: Decimal, next_entries: list[_Entry], dial: Decimal
) -> None:
```

y reemplazar el loop final del paso 3 por:

```python
    for e in candidates:
        if surplus <= 0:
            break
        reserve = _lookahead_reserve(entries, next_entries, e.financing_rate * 2, dial)
        budget = surplus - reserve
        if budget <= 0:
            continue
        pay = min(e.saldo * e.fx, budget)
        e.decided += (pay / e.fx).quantize(Q, rounding=ROUND_DOWN)  # nunca pasarse del sobrante
        surplus = capacity - _spent(entries)
```

3. En `run_planning`, actualizar la llamada (el `idx` pasa arriba para reusar `next_entries`):

```python
        capacity = available + _pending_income(month_entries) - remaining
        idx = months.index(m)
        next_entries = by_month[months[idx + 1]] if idx + 1 < len(months) else []
        _allocate_month(month_entries, capacity, next_entries, dial)
        prev_balance = capacity - _spent(month_entries)
        _apply_carry(month_entries, next_entries)
```

- [ ] **Step 4: Verificar que pasa**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: PASS (19 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/planning/engine.py tests/test_planning.py
git commit -m "feat(planning): look-ahead de un mes con umbral 2X"
```

---

### Task 7: Regeneración idempotente

**Files:**
- Test: `backend/tests/test_planning.py` (la implementación ya existe desde Task 2; esto la verifica de punta a punta)

- [ ] **Step 1: Test**

Agregar a `backend/tests/test_planning.py`:

```python
# --- regeneración ---

def test_recorrida_borra_solo_autos_y_es_idempotente(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="2000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="300.00")
    manual = _pay(db_session, card, "50.00", plan_id=plan.id, planned_date=date(2026, 6, 22))

    run_planning(db_session, user, plan.id, today=TODAY)
    primera = _autos(db_session, plan)
    run_planning(db_session, user, plan.id, today=TODAY)
    segunda = _autos(db_session, plan)

    # manual 50 < minimo 300 -> el motor completa: fila auto = 300 - 50 = 250
    assert [a.amount for a in primera] == [Decimal("250.00")]
    assert [a.amount for a in segunda] == [Decimal("250.00")]
    assert primera[0].id != segunda[0].id  # regeneradas, no reusadas
    assert db_session.get(CashFlowPayment, manual.id) is not None  # el manual sobrevive
```

- [ ] **Step 2: Verificar que pasa**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: PASS (20 tests). Si falla, el bug está en el orden borrado/carga o en que `_payment_sums` está contando filas auto como manuales.

- [ ] **Step 3: Commit**

```bash
git add tests/test_planning.py
git commit -m "test(planning): regeneracion idempotente y manuales sobreviven"
```

---

### Task 8: Verificación final

- [ ] **Step 1: Suite completa**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest -q`
Expected: todo PASS, ningún test existente roto.

- [ ] **Step 2: Smoke manual contra la base dev (caso de referencia del spec §9)**

Con el backend corriendo y datos dev del usuario `5309521d-...`: correr `POST /plans/a07c64a7-2b3b-443c-b9c6-2240ea5940d1/planning` autenticado como ese usuario y verificar contra el spec §9:

- En junio quedan filas auto coherentes con la corrida de referencia (cap de la tarjeta con pago real parcial, mínimos de las tarjetas USD retenidas por el look-ahead).
- `GET /cash-flow-entries?plan_id=...` refleja los `planned_amount` y el balance de junio queda ≈ la reserva del look-ahead.
- Volver a correr el endpoint: misma cantidad de filas (idempotente).

Nota: los montos exactos del §9 dependen del estado de la base dev al momento (pagos/manuales que se hayan agregado); validar la *forma* de la decisión (qué queda al mínimo, dónde cae el parcial), no centavos.

- [ ] **Step 3: Limpiar los pagos auto de prueba en dev (si se corrió el smoke)**

```bash
psql -d margin -c "DELETE FROM cash_flow_payments WHERE plan_id='a07c64a7-2b3b-443c-b9c6-2240ea5940d1' AND is_auto_generated;"
```

(O dejarlos: son regenerables con otra corrida. A criterio del usuario.)

- [ ] **Step 4: Terminar la rama**

Usar superpowers:finishing-a-development-branch (squash-merge a `main`, push manual — convención del repo).
