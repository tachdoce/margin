# cash_flow_payments CRUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Los 4 endpoints de `cash_flow_payments` (POST/GET/PATCH/DELETE) anidados bajo
`/cash-flow-entries/{entry_id}/payments`.

**Architecture:** Router thin → service (valida, controla commit, levanta `AppError`) → modelos existentes
`CashFlowEntry`/`CashFlowPayment`. Pertenencia por `cfe.user_id` directo. Pagabilidad codificada "la excepción
es la entry de plan" (todo lo demás, incl. `tarjeta_credito`, es real).

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest.

**Spec:** `docs/superpowers/specs/2026-06-09-cash-flow-payments-design.md`

**Branch:** `feat/cash-flow-payments` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

**Notas de patrón (ya verificadas en el repo):**
- `errors.py`: `ErrorCode` es un `Enum` de tuplas `(status, message)`. `amount_invalid` y `empty_patch`
  **ya existen** (reusar, no duplicar). `not_found`, `unauthenticated` también.
- Service: funciones `(db, user, ...)`, `raise AppError(ErrorCode.x, field=...)`, `db.flush()` + `db.commit()`,
  devuelven el modelo. Router usa `response_model` + un `from_model` en el schema.
- Pydantic v2 serializa `Decimal` como string (sin config especial; igual que `CreditCardOut`).
- Modelos: `CashFlowEntry` (`id, user_id, source_type, source_id, amount, currency_id, is_income, event_date`),
  `CashFlowPayment` (`id, cash_flow_entry_id, amount, note, plan_id, planned_date, created_at, updated_at`),
  `Plan` (`id, user_id`), `PlanMovement` (`id, plan_id`).
- Tests: helper `_auth(client, email="u@b.com")` (registra y devuelve headers) y `_last_user(db_session)`
  (último user). Postgres `margin_test`, `create_all` + savepoint.

---

## File Structure

| Archivo | Cambio |
|---|---|
| `app/core/errors.py` | + 6 codes nuevos |
| `app/schemas/cash_flow_payment.py` | Create / Update / Out / ListItem |
| `app/services/cash_flow_payment_service.py` | create/list/update/delete + helpers |
| `app/routers/cash_flow_payments.py` | router thin (4 rutas) |
| `app/main.py` | registrar el router |
| `tests/test_cash_flow_payments_create.py` | POST |
| `tests/test_cash_flow_payments_list.py` | GET |
| `tests/test_cash_flow_payments_update.py` | PATCH |
| `tests/test_cash_flow_payments_delete.py` | DELETE |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/cash-flow-payments
```

---

## Task 1: Errores + schemas + service (create + helpers) + router + POST

**Files:**
- Modify: `app/core/errors.py`, `app/main.py`
- Create: `app/schemas/cash_flow_payment.py`, `app/services/cash_flow_payment_service.py`,
  `app/routers/cash_flow_payments.py`, `tests/test_cash_flow_payments_create.py`

- [ ] **Step 1: Agregar los códigos de error** en `app/core/errors.py`, dentro del `class ErrorCode`, después
  de `card_not_deleted`:

```python
    entry_not_payable = (409, "Esta entrada no acepta este pago.")
    planned_payment_incomplete = (422, "Un pago planificado necesita plan y fecha.")
    plan_id_required = (422, "Falta indicar el plan.")
    month_invalid = (422, "El mes indicado no es válido.")
    planned_date_on_real_payment = (422, "No se puede agendar fecha en un pago real.")
    planned_date_invalid = (422, "La fecha agendada no es válida.")
```

- [ ] **Step 2: Crear los schemas** `app/schemas/cash_flow_payment.py`:

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.cash_flow_payment import CashFlowPayment


class PaymentCreate(BaseModel):
    amount: Decimal
    note: str | None = None
    plan_id: uuid.UUID | None = None
    planned_date: date | None = None


class PaymentUpdate(BaseModel):
    amount: Decimal | None = None
    note: str | None = None
    planned_date: date | None = None


class PaymentOut(BaseModel):
    id: uuid.UUID
    cash_flow_entry_id: uuid.UUID
    amount: Decimal
    note: str | None
    plan_id: uuid.UUID | None
    planned_date: date | None
    created_at: datetime

    @classmethod
    def from_model(cls, p: CashFlowPayment) -> "PaymentOut":
        return cls(
            id=p.id,
            cash_flow_entry_id=p.cash_flow_entry_id,
            amount=p.amount,
            note=p.note,
            plan_id=p.plan_id,
            planned_date=p.planned_date,
            created_at=p.created_at,
        )


class PaymentListItem(BaseModel):
    id: uuid.UUID
    cash_flow_entry_id: uuid.UUID
    amount: Decimal
    note: str | None
    is_planned: bool
    planned_date: date | None
    created_at: datetime

    @classmethod
    def from_model(cls, p: CashFlowPayment) -> "PaymentListItem":
        return cls(
            id=p.id,
            cash_flow_entry_id=p.cash_flow_entry_id,
            amount=p.amount,
            note=p.note,
            is_planned=p.plan_id is not None,
            planned_date=p.planned_date,
            created_at=p.created_at,
        )
```

- [ ] **Step 3: Crear el service** `app/services/cash_flow_payment_service.py` (por ahora helpers + `create`):

```python
import uuid
from datetime import date, datetime

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.schemas.cash_flow_payment import PaymentCreate, PaymentUpdate

PLAN_ENTRY_TYPES = {"plan_movimiento", "plan_movimiento_entrada"}


def _load_owned_entry(db: Session, user: User, entry_id: uuid.UUID) -> CashFlowEntry:
    entry = db.get(CashFlowEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    return entry


def _load_owned_plan(db: Session, user: User, plan_id: uuid.UUID) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    return plan


def _is_plan_entry(entry: CashFlowEntry) -> bool:
    return entry.source_type in PLAN_ENTRY_TYPES


def _entry_plan_id(db: Session, entry: CashFlowEntry) -> uuid.UUID | None:
    # solo tiene sentido para entries de plan: sube source_id -> plan_movements.plan_id
    pm = db.get(PlanMovement, entry.source_id)
    return pm.plan_id if pm else None


def _load_owned_payment(db: Session, entry: CashFlowEntry, payment_id: uuid.UUID) -> CashFlowPayment:
    payment = db.get(CashFlowPayment, payment_id)
    if payment is None or payment.cash_flow_entry_id != entry.id:
        raise AppError(ErrorCode.not_found)
    return payment


def create_payment(db: Session, user: User, entry_id: uuid.UUID, payload: PaymentCreate) -> CashFlowPayment:
    entry = _load_owned_entry(db, user, entry_id)

    # coherencia plan_id / planned_date: ambos o ninguno
    if (payload.plan_id is None) != (payload.planned_date is None):
        raise AppError(ErrorCode.planned_payment_incomplete)

    if payload.plan_id is not None:
        _load_owned_plan(db, user, payload.plan_id)

    # pagabilidad: la excepción es la entry de plan
    if payload.plan_id is None:
        # pago real: solo contra entries que NO son de plan
        if _is_plan_entry(entry):
            raise AppError(ErrorCode.entry_not_payable)
    else:
        # pago planificado: entry real -> ok; entry de plan -> mismo plan
        if _is_plan_entry(entry) and _entry_plan_id(db, entry) != payload.plan_id:
            raise AppError(ErrorCode.entry_not_payable)

    if payload.amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")

    payment = CashFlowPayment(
        cash_flow_entry_id=entry.id,
        amount=payload.amount,
        note=payload.note,
        plan_id=payload.plan_id,
        planned_date=payload.planned_date,
    )
    db.add(payment)
    db.flush()
    db.commit()
    db.refresh(payment)
    return payment
```

- [ ] **Step 4: Crear el router** `app/routers/cash_flow_payments.py` (por ahora solo POST):

```python
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.cash_flow_payment import PaymentCreate, PaymentOut
from app.services import cash_flow_payment_service as svc

router = APIRouter(tags=["cash-flow-payments"])


@router.post(
    "/cash-flow-entries/{entry_id}/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_payment(
    entry_id: uuid.UUID,
    payload: PaymentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOut:
    return PaymentOut.from_model(svc.create_payment(db, user, entry_id, payload))
```

- [ ] **Step 5: Registrar el router** en `app/main.py` (junto a los demás `include_router`):

```python
from app.routers import cash_flow_payments
```
```python
app.include_router(cash_flow_payments.router)
```

- [ ] **Step 6: Escribir los tests del POST** `tests/test_cash_flow_payments_create.py`:

```python
import uuid

from app.models.cash_flow_entry import CashFlowEntry
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    from app.models.user import User
    return db_session.execute(__import__("sqlalchemy").select(User).order_by(User.created_at.desc())).scalars().first()


def _make_entry(db_session, user, *, source_type="gasto", source_id=None, is_income=False, amount="6000.00"):
    from decimal import Decimal
    entry = CashFlowEntry(
        user_id=user.id,
        event_date=None,
        is_income=is_income,
        amount=Decimal(amount),
        currency_id=1,
        source_type=source_type,
        source_id=source_id or uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _make_plan(db_session, user):
    plan = Plan(user_id=user.id)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _make_plan_entry(db_session, user, plan):
    pm = PlanMovement(plan_id=plan.id)
    db_session.add(pm)
    db_session.commit()
    db_session.refresh(pm)
    entry = _make_entry(db_session, user, source_type="plan_movimiento", source_id=pm.id)
    return entry


def test_create_real_payment(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "4500.00", "note": "transf"}, headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["amount"] == "4500.00"
    assert body["plan_id"] is None
    assert body["planned_date"] is None
    assert body["cash_flow_entry_id"] == str(entry.id)


def test_create_planned_payment(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    r = client.post(
        f"/cash-flow-entries/{entry.id}/payments",
        json={"amount": "5000.00", "plan_id": str(plan.id), "planned_date": "2026-07-15"},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.json()["plan_id"] == str(plan.id)
    assert r.json()["planned_date"] == "2026-07-15"


def test_create_entry_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    r = client.post(f"/cash-flow-entries/{uuid.uuid4()}/payments", json={"amount": "10.00"}, headers=headers)
    assert r.status_code == 404


def test_create_entry_of_other_user(client, db_session, seed_uy_currency):
    headers_a = _headers(client, email="a@b.com")
    user_a = _last_user(db_session)
    entry = _make_entry(db_session, user_a)
    headers_b = _headers(client, email="b@b.com")
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "10.00"}, headers=headers_b)
    assert r.status_code == 404


def test_create_plan_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    r = client.post(
        f"/cash-flow-entries/{entry.id}/payments",
        json={"amount": "10.00", "plan_id": str(uuid.uuid4()), "planned_date": "2026-07-15"},
        headers=headers,
    )
    assert r.status_code == 404


def test_create_planned_incomplete(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "10.00", "planned_date": "2026-07-15"}, headers=headers)
    assert r.json()["code"] == "planned_payment_incomplete"


def test_create_real_against_plan_entry_409(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _make_plan(db_session, user)
    entry = _make_plan_entry(db_session, user, plan)
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "10.00"}, headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "entry_not_payable"


def test_create_planned_wrong_plan_409(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    plan_a = _make_plan(db_session, user)
    plan_b = _make_plan(db_session, user)
    entry = _make_plan_entry(db_session, user, plan_a)
    r = client.post(
        f"/cash-flow-entries/{entry.id}/payments",
        json={"amount": "10.00", "plan_id": str(plan_b.id), "planned_date": "2026-07-15"},
        headers=headers,
    )
    assert r.json()["code"] == "entry_not_payable"


def test_create_planned_against_real_entry_ok(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)  # real
    plan = _make_plan(db_session, user)
    r = client.post(
        f"/cash-flow-entries/{entry.id}/payments",
        json={"amount": "10.00", "plan_id": str(plan.id), "planned_date": "2026-07-15"},
        headers=headers,
    )
    assert r.status_code == 201


def test_create_real_against_credit_card_entry_ok(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user, source_type="tarjeta_credito")
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "100.00"}, headers=headers)
    assert r.status_code == 201


def test_create_amount_invalid(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    assert client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "0"}, headers=headers).json()["code"] == "amount_invalid"
    assert client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "-5"}, headers=headers).json()["code"] == "amount_invalid"
```

- [ ] **Step 7: Run → rojo, luego verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_flow_payments_create.py -q
```

Primero deben fallar; tras Steps 1-5 ya implementados, deben pasar. (Si escribís el test antes que el código,
verás el rojo; ejecutá de nuevo tras implementar para el verde.)

- [ ] **Step 8: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/core/errors.py app/schemas/cash_flow_payment.py app/services/cash_flow_payment_service.py app/routers/cash_flow_payments.py app/main.py tests/test_cash_flow_payments_create.py && git commit -m "feat: POST cash-flow-entries/{id}/payments"
```

---

## Task 2: GET (listar pagos)

**Files:**
- Modify: `app/services/cash_flow_payment_service.py`, `app/routers/cash_flow_payments.py`
- Create: `tests/test_cash_flow_payments_list.py`

- [ ] **Step 1: Agregar `list_payments` al service** (`cash_flow_payment_service.py`):

```python
def _parse_month(month: str) -> date:
    try:
        return datetime.strptime(month, "%Y-%m").date().replace(day=1)
    except (ValueError, TypeError):
        raise AppError(ErrorCode.month_invalid)


def list_payments(
    db: Session, user: User, entry_id: uuid.UUID, plan_id: uuid.UUID | None, month: str | None
) -> list[CashFlowPayment]:
    if plan_id is None:
        raise AppError(ErrorCode.plan_id_required)
    month_start = _parse_month(month) if month is not None else None
    entry = _load_owned_entry(db, user, entry_id)
    _load_owned_plan(db, user, plan_id)

    stmt = select(CashFlowPayment).where(
        CashFlowPayment.cash_flow_entry_id == entry.id,
        (CashFlowPayment.plan_id.is_(None)) | (CashFlowPayment.plan_id == plan_id),
    )
    if month_start is not None:
        bucket = func.date_trunc(
            "month", func.coalesce(CashFlowPayment.planned_date, cast(CashFlowPayment.created_at, Date))
        )
        stmt = stmt.where(bucket == month_start)
    stmt = stmt.order_by(CashFlowPayment.created_at.desc())
    return list(db.execute(stmt).scalars())
```

- [ ] **Step 2: Agregar la ruta GET al router** (`cash_flow_payments.py`). Añadir el import de `Query` y
  `PaymentListItem`, y la función:

```python
from fastapi import APIRouter, Depends, Query, status
```
```python
from app.schemas.cash_flow_payment import PaymentCreate, PaymentListItem, PaymentOut
```
```python
@router.get("/cash-flow-entries/{entry_id}/payments")
def list_payments(
    entry_id: uuid.UUID,
    plan_id: uuid.UUID | None = Query(default=None),
    month: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PaymentListItem]:
    rows = svc.list_payments(db, user, entry_id, plan_id, month)
    return [PaymentListItem.from_model(p) for p in rows]
```

- [ ] **Step 3: Tests** `tests/test_cash_flow_payments_list.py` (reusar los helpers; copiá `_headers`,
  `_last_user`, `_make_entry`, `_make_plan` como en Task 1):

```python
import uuid
from decimal import Decimal

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    from sqlalchemy import select
    from app.models.user import User
    return db_session.execute(select(User).order_by(User.created_at.desc())).scalars().first()


def _make_entry(db_session, user):
    entry = CashFlowEntry(
        user_id=user.id, event_date=None, is_income=False, amount=Decimal("6000.00"),
        currency_id=1, source_type="gasto", source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _make_plan(db_session, user):
    plan = Plan(user_id=user.id)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _pay(db_session, entry, *, amount="100.00", plan_id=None, planned_date=None):
    p = CashFlowPayment(
        cash_flow_entry_id=entry.id, amount=Decimal(amount), plan_id=plan_id, planned_date=planned_date
    )
    db_session.add(p)
    db_session.commit()
    return p


def test_list_requires_plan_id(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    assert client.get(f"/cash-flow-entries/{entry.id}/payments", headers=headers).json()["code"] == "plan_id_required"


def test_list_month_invalid(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    r = client.get(f"/cash-flow-entries/{entry.id}/payments?plan_id={plan.id}&month=2026-13-99", headers=headers)
    assert r.json()["code"] == "month_invalid"


def test_list_real_plus_this_plan_excludes_others(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    other = _make_plan(db_session, user)
    from datetime import date
    _pay(db_session, entry, amount="1.00")  # real
    _pay(db_session, entry, amount="2.00", plan_id=plan.id, planned_date=date(2026, 7, 15))  # de este plan
    _pay(db_session, entry, amount="3.00", plan_id=other.id, planned_date=date(2026, 7, 15))  # de otro plan
    rows = client.get(f"/cash-flow-entries/{entry.id}/payments?plan_id={plan.id}", headers=headers).json()
    amounts = {r["amount"] for r in rows}
    assert amounts == {"1.00", "2.00"}
    by_amount = {r["amount"]: r for r in rows}
    assert by_amount["1.00"]["is_planned"] is False
    assert by_amount["2.00"]["is_planned"] is True


def test_list_month_filter(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    from datetime import date
    _pay(db_session, entry, amount="2.00", plan_id=plan.id, planned_date=date(2026, 7, 15))  # julio
    _pay(db_session, entry, amount="3.00", plan_id=plan.id, planned_date=date(2026, 8, 1))   # agosto
    rows = client.get(f"/cash-flow-entries/{entry.id}/payments?plan_id={plan.id}&month=2026-07", headers=headers).json()
    assert {r["amount"] for r in rows} == {"2.00"}


def test_list_empty(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    assert client.get(f"/cash-flow-entries/{entry.id}/payments?plan_id={plan.id}", headers=headers).json() == []
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_flow_payments_list.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_payment_service.py app/routers/cash_flow_payments.py tests/test_cash_flow_payments_list.py && git commit -m "feat: GET cash-flow-entries/{id}/payments"
```

---

## Task 3: PATCH (editar pago)

**Files:**
- Modify: `app/services/cash_flow_payment_service.py`, `app/routers/cash_flow_payments.py`
- Create: `tests/test_cash_flow_payments_update.py`

- [ ] **Step 1: Agregar `update_payment` al service**:

```python
def update_payment(
    db: Session, user: User, entry_id: uuid.UUID, payment_id: uuid.UUID, payload: PaymentUpdate
) -> CashFlowPayment:
    entry = _load_owned_entry(db, user, entry_id)
    payment = _load_owned_payment(db, entry, payment_id)

    fields = payload.model_fields_set
    if not fields & {"amount", "note", "planned_date"}:
        raise AppError(ErrorCode.empty_patch)

    if "amount" in fields:
        if payload.amount is None or payload.amount <= 0:
            raise AppError(ErrorCode.amount_invalid, field="amount")
        payment.amount = payload.amount

    if "note" in fields:
        payment.note = payload.note

    if "planned_date" in fields:
        if payment.plan_id is None:
            raise AppError(ErrorCode.planned_date_on_real_payment, field="planned_date")
        if payload.planned_date is None:
            raise AppError(ErrorCode.planned_date_invalid, field="planned_date")
        payment.planned_date = payload.planned_date

    db.flush()
    db.commit()
    db.refresh(payment)
    return payment
```

- [ ] **Step 2: Ruta PATCH en el router**. Importar `PaymentUpdate` y agregar:

```python
from app.schemas.cash_flow_payment import PaymentCreate, PaymentListItem, PaymentOut, PaymentUpdate
```
```python
@router.patch("/cash-flow-entries/{entry_id}/payments/{payment_id}", response_model=PaymentOut)
def update_payment(
    entry_id: uuid.UUID,
    payment_id: uuid.UUID,
    payload: PaymentUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOut:
    return PaymentOut.from_model(svc.update_payment(db, user, entry_id, payment_id, payload))
```

- [ ] **Step 3: Tests** `tests/test_cash_flow_payments_update.py` (copiar helpers `_headers`, `_last_user`,
  `_make_entry`, `_make_plan`, `_pay` como en Task 2):

```python
import uuid
from datetime import date
from decimal import Decimal

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    from sqlalchemy import select
    from app.models.user import User
    return db_session.execute(select(User).order_by(User.created_at.desc())).scalars().first()


def _make_entry(db_session, user):
    entry = CashFlowEntry(
        user_id=user.id, event_date=None, is_income=False, amount=Decimal("6000.00"),
        currency_id=1, source_type="gasto", source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _make_plan(db_session, user):
    plan = Plan(user_id=user.id)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _pay(db_session, entry, *, amount="100.00", note=None, plan_id=None, planned_date=None):
    p = CashFlowPayment(
        cash_flow_entry_id=entry.id, amount=Decimal(amount), note=note, plan_id=plan_id, planned_date=planned_date
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def test_patch_amount(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry, amount="100.00")
    r = client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"amount": "150.00"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["amount"] == "150.00"


def test_patch_note_to_null(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry, note="algo")
    r = client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"note": None}, headers=headers)
    assert r.status_code == 200
    assert r.json()["note"] is None


def test_patch_empty(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry)
    assert client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={}, headers=headers).json()["code"] == "empty_patch"


def test_patch_amount_invalid(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry)
    assert client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"amount": "0"}, headers=headers).json()["code"] == "amount_invalid"


def test_patch_planned_date_on_real(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry)  # real
    r = client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"planned_date": "2026-07-15"}, headers=headers)
    assert r.json()["code"] == "planned_date_on_real_payment"


def test_patch_reschedule_planned(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    p = _pay(db_session, entry, plan_id=plan.id, planned_date=date(2026, 7, 15))
    r = client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"planned_date": "2026-08-01"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["planned_date"] == "2026-08-01"


def test_patch_planned_date_null_on_planned(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    p = _pay(db_session, entry, plan_id=plan.id, planned_date=date(2026, 7, 15))
    assert client.patch(f"/cash-flow-entries/{entry.id}/payments/{p.id}", json={"planned_date": None}, headers=headers).json()["code"] == "planned_date_invalid"


def test_patch_payment_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    assert client.patch(f"/cash-flow-entries/{entry.id}/payments/{uuid.uuid4()}", json={"amount": "1"}, headers=headers).status_code == 404
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_flow_payments_update.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_payment_service.py app/routers/cash_flow_payments.py tests/test_cash_flow_payments_update.py && git commit -m "feat: PATCH cash-flow-entries/{id}/payments/{pid}"
```

---

## Task 4: DELETE (anular pago)

**Files:**
- Modify: `app/services/cash_flow_payment_service.py`, `app/routers/cash_flow_payments.py`
- Create: `tests/test_cash_flow_payments_delete.py`

- [ ] **Step 1: Agregar `delete_payment` al service**:

```python
def delete_payment(db: Session, user: User, entry_id: uuid.UUID, payment_id: uuid.UUID) -> None:
    entry = _load_owned_entry(db, user, entry_id)
    payment = _load_owned_payment(db, entry, payment_id)
    db.delete(payment)
    db.commit()
```

- [ ] **Step 2: Ruta DELETE en el router**:

```python
@router.delete(
    "/cash-flow-entries/{entry_id}/payments/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_payment(
    entry_id: uuid.UUID,
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    svc.delete_payment(db, user, entry_id, payment_id)
```

- [ ] **Step 3: Tests** `tests/test_cash_flow_payments_delete.py` (copiar helpers `_headers`, `_last_user`,
  `_make_entry`, `_make_plan`, `_pay`):

```python
import uuid
from datetime import date
from decimal import Decimal

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    from sqlalchemy import select
    from app.models.user import User
    return db_session.execute(select(User).order_by(User.created_at.desc())).scalars().first()


def _make_entry(db_session, user):
    entry = CashFlowEntry(
        user_id=user.id, event_date=None, is_income=False, amount=Decimal("6000.00"),
        currency_id=1, source_type="gasto", source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _make_plan(db_session, user):
    plan = Plan(user_id=user.id)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _pay(db_session, entry, *, amount="100.00", plan_id=None, planned_date=None):
    p = CashFlowPayment(
        cash_flow_entry_id=entry.id, amount=Decimal(amount), plan_id=plan_id, planned_date=planned_date
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def test_delete_real(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    p = _pay(db_session, entry)
    r = client.delete(f"/cash-flow-entries/{entry.id}/payments/{p.id}", headers=headers)
    assert r.status_code == 204
    assert db_session.get(CashFlowPayment, p.id) is None


def test_delete_planned(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    p = _pay(db_session, entry, plan_id=plan.id, planned_date=date(2026, 7, 15))
    assert client.delete(f"/cash-flow-entries/{entry.id}/payments/{p.id}", headers=headers).status_code == 204


def test_delete_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    assert client.delete(f"/cash-flow-entries/{entry.id}/payments/{uuid.uuid4()}", headers=headers).status_code == 404


def test_delete_payment_of_other_entry(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry_a = _make_entry(db_session, user)
    entry_b = _make_entry(db_session, user)
    p = _pay(db_session, entry_a)
    assert client.delete(f"/cash-flow-entries/{entry_b.id}/payments/{p.id}", headers=headers).status_code == 404
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_flow_payments_delete.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_payment_service.py app/routers/cash_flow_payments.py tests/test_cash_flow_payments_delete.py && git commit -m "feat: DELETE cash-flow-entries/{id}/payments/{pid}"
```

---

## Task 5: Suite completa + Notion + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (los 448 previos + los nuevos de pagos).

- [ ] **Step 2: Actualizar Notion** (lo hace el coordinador, no el subagente): en
  `Endpoints → Flujo de dinero → POST cash-flow-payments` y `GET cash-flow-payments`, incluir
  `tarjeta_credito` entre los tipos reales y reformular la regla como "la excepción es la entry de plan".

- [ ] **Step 3: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre
  esperado: **squash-merge** de `feat/cash-flow-payments` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** schemas (Task 1), 6 codes nuevos sin duplicar `amount_invalid`/`empty_patch` (Task 1),
  POST + pagabilidad incl. tarjeta_credito (Task 1), GET con plan_id obligatorio + month + is_planned (Task 2),
  PATCH con reglas de planned_date sobre la fila guardada (Task 3), DELETE físico (Task 4), Notion (Task 5). ✓
- **Placeholder scan:** sin TBD/TODO ni código roto. ✓
- **Consistencia de tipos:** `PaymentOut` (POST/PATCH, con `plan_id`/`planned_date`), `PaymentListItem` (GET,
  con `is_planned`); service `create/list/update/delete` con firmas usadas por el router; helpers
  `_load_owned_entry/_load_owned_plan/_load_owned_payment/_is_plan_entry/_entry_plan_id` definidos en Task 1. ✓
- **Riesgo conocido:** `PlanMovement(plan_id=...)` y `Plan(user_id=...)` — si esos modelos exigen más columnas
  NOT NULL al insertarlos en los tests, el implementer completa los kwargs mínimos (mirar el modelo). Lo mismo
  para `CashFlowEntry` (ya cubre los NOT NULL: user_id, is_income, amount, currency_id, source_type, source_id).
