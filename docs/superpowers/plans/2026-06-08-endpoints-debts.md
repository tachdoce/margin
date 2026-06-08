# Endpoints de debts (6b) — Plan de implementación

> **For agentic workers:** Ejecutar según el modo que elija el usuario (inline o subagente con higiene de
> comandos: `cd` no `git -C`, sin `2>&1`). TDD: test → rojo → implementación → verde → commit por task.

**Goal:** Los 3 endpoints de deudas (`POST/PATCH/GET debts`), cubriendo 2 kinds (`deuda` / `deuda_abierta`),
cableando validación por kind → `review_obligation` → `materialize_debt`/`materialize_open_debt`.

**Architecture:** Router finito → `debt_service` → modelo `Obligation`. Orquestación uniforme (reviewer
siempre; el `is_closed` lo maneja el reviewer). Motor elegido por kind. Reusa `require_user_currency`,
`review_obligation`, `materialize_debt`, `materialize_open_debt`. Validadores comunes replicados de
`expense_service` (extracción diferida a post-6c).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, pytest. Spec:
`docs/superpowers/specs/2026-06-08-endpoints-debts-design.md`.

**Rama:** `feat/endpoints-debts` → squash-merge a `main`.

---

## Task 0: Crear la rama

- [ ] **Step 1:**

```bash
git checkout -b feat/endpoints-debts
```

---

## Task 1: Error codes + schemas + servicio + POST + GET + router

**Files:**
- Modify: `backend/app/core/errors.py`
- Create: `backend/app/schemas/debt.py`
- Create: `backend/app/services/debt_service.py`
- Create: `backend/app/routers/debts.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_debts.py`

- [ ] **Step 1: Agregar error codes**

En `backend/app/core/errors.py`, dentro del enum `ErrorCode` (tras los de expenses):

```python
    debt_type_invalid = (422, "Tipo de deuda no válido.")
    institution_invalid = (422, "Institución no válida.")
    rates_negative = (422, "Las tasas no pueden ser negativas.")
    one_time_debt_inconsistent = (422, "Una deuda de un pago no admite día de vencimiento ni cuotas.")
    debt_requires_schedule_or_date = (422, "Una deuda necesita un cronograma o una fecha de pago.")
    open_debt_inconsistent = (422, "Una deuda abierta no admite fechas, cuotas ni tasas.")
    debt_schedule_requires_due_day = (422, "Una deuda en cuotas necesita un día de vencimiento.")
    debt_schedule_locked = (409, "No se puede cambiar el cronograma de una deuda con pagos registrados.")
```
(`installments_invalid`, `priority_level_invalid`, `description_invalid`, `amount_invalid`, `due_day_invalid`,
`currency_not_available`, `not_found`, `field_not_nullable` ya existen.)

- [ ] **Step 2: Escribir los tests de POST y GET (rojo)**

`backend/tests/test_debts.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.country import Country
from app.models.currency import Currency
from app.models.institution import Institution
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel

CRON_FIRST = (date.today() + timedelta(days=20)).isoformat()   # cronograma: arranca futuro
ONE_TIME = (date.today() + timedelta(days=60)).isoformat()     # pago único futuro


@pytest.fixture
def catalog(db_session, seed_uy_currency):
    db_session.add_all([
        PriorityLevel(level=1, name="Ineludible", description="x"),
        PriorityLevel(level=3, name="Crítica", description="x"),
        PriorityLevel(level=4, name="Prioritaria", description="x"),
        PriorityLevel(level=5, name="Manejable", description="x"),
    ])
    db_session.flush()
    db_session.add_all([
        ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                       description="x", default_priority_level=5, visible=True),
        ObligationType(id=8, obligation_kind="deuda_abierta", code="informal", name="Informal",
                       description="x", default_priority_level=3, visible=True),
        ObligationType(id=9, obligation_kind="deuda_abierta", code="otra_abierta", name="Otra",
                       description="x", default_priority_level=3, visible=True),  # no-informal
        ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                       description="x", default_priority_level=3, visible=True),
    ])
    db_session.flush()
    db_session.add(Institution(id=1, country_code="UY", name="Banco UY", visible=True))
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _cronograma(**over):
    body = {
        "obligation_type_id": 10, "priority_level": 5, "institution_id": 1,
        "description": "Préstamo personal banco", "due_day": 10, "currency_id": 1,
        "amount": "6250.00", "total_installments": 24, "first_due_date": CRON_FIRST,
        "financing_rate": "45.00", "overdue_rate": "60.00", "rates_add_vat": True,
    }
    body.update(over)
    return body


def _pago_unico(**over):
    body = {
        "obligation_type_id": 10, "priority_level": 4, "description": "Préstamo familiar",
        "currency_id": 1, "amount": "30000.00", "first_due_date": ONE_TIME,
    }
    body.update(over)
    return body


def _abierta(**over):
    body = {
        "obligation_type_id": 8, "priority_level": 3, "description": "Plata que le debo a mi viejo",
        "currency_id": 1, "amount": "50000.00",
    }
    body.update(over)
    return body


def _entries(db_session, obligation_id, source_type="deuda"):
    return list(db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_type == source_type,
                                    CashFlowEntry.source_id == obligation_id)
    ).scalars())


# --- POST deuda ---

def test_post_cronograma_materializa(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_monthly_recurring"] is False
    assert body["total_installments"] == 24
    assert body["financing_rate"] == "45.00"
    assert body["review_findings"] == []
    assert body["is_ready"] is True
    assert len(_entries(db_session, body["id"])) > 0


def test_post_pago_unico_una_entry(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_pago_unico(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["total_installments"] is None
    assert body["due_day"] is None
    assert len(_entries(db_session, body["id"])) == 1


def test_post_abierta_una_entry_sin_fecha(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_abierta(institution_id=1), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["institution_id"] is None  # se ignora en deuda_abierta
    assert body["first_due_date"] is None
    entries = _entries(db_session, body["id"], source_type="deuda_abierta")
    assert len(entries) == 1
    assert entries[0].event_date is None


def test_post_con_findings_no_materializa(client, db_session, catalog):
    headers = _auth(client)
    # overdue < financing → finding overdue_lower_than_financing
    resp = client.post("/debts", json=_cronograma(financing_rate="45.00", overdue_rate="30.00"),
                       headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["review_findings"] == ["overdue_lower_than_financing"]
    assert body["is_ready"] is False
    assert _entries(db_session, body["id"]) == []  # no materializó


# --- POST errores ---

def test_post_kind_gasto_rechazado(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(obligation_type_id=1), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_type_invalid"


def test_post_abierta_tipo_no_informal(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_abierta(obligation_type_id=9), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_type_invalid"


def test_post_priority_sistema(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(priority_level=1), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "priority_level_invalid"


def test_post_institution_otro_pais(client, db_session, catalog):
    db_session.add(Country(code="AR", name="Argentina", visible=True, vat_rate=Decimal("21.00")))
    db_session.flush()
    db_session.add(Institution(id=2, country_code="AR", name="Banco AR", visible=True))
    db_session.flush()
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(institution_id=2), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "institution_invalid"


def test_post_deuda_sin_first_due_date(client, db_session, catalog):
    headers = _auth(client)
    body = _cronograma()
    del body["first_due_date"]
    resp = client.post("/debts", json=body, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_requires_schedule_or_date"


def test_post_cronograma_sin_due_day(client, db_session, catalog):
    headers = _auth(client)
    body = _cronograma()
    del body["due_day"]
    resp = client.post("/debts", json=body, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_schedule_requires_due_day"


def test_post_installments_cero(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(total_installments=0), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "installments_invalid"


def test_post_pago_unico_con_due_day(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_pago_unico(due_day=10), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "one_time_debt_inconsistent"


def test_post_tasa_negativa(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(financing_rate="-1.00"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "rates_negative"


def test_post_abierta_con_fecha(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_abierta(first_due_date=ONE_TIME), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "open_debt_inconsistent"


def test_post_sin_token(client, db_session, catalog):
    assert client.post("/debts", json=_cronograma()).status_code == 401


# --- GET ---

def test_get_lista_ambos_kinds(client, db_session, catalog):
    headers = _auth(client)
    client.post("/debts", json=_cronograma(), headers=headers)
    client.post("/debts", json=_abierta(), headers=headers)
    resp = client.get("/debts", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["debts"]) == 2


def test_get_vacio(client, db_session, catalog):
    headers = _auth(client)
    assert client.get("/debts", headers=headers).json() == {"debts": []}


def test_get_sin_token(client, db_session, catalog):
    assert client.get("/debts").status_code == 401
```

- [ ] **Step 3: Correr, verificar que fallan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_debts.py -q
```
Esperado: FAIL.

- [ ] **Step 4: Crear el schema**

`backend/app/schemas/debt.py`:

```python
import json
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.obligation import Obligation


class DebtCreate(BaseModel):
    obligation_type_id: int
    priority_level: int
    institution_id: int | None = None
    description: str
    due_day: int | None = None
    currency_id: int
    amount: Decimal
    total_installments: int | None = None
    first_due_date: date | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool | None = None
    shift_weekends: bool | None = None


class DebtUpdate(BaseModel):
    obligation_type_id: int | None = None
    priority_level: int | None = None
    institution_id: int | None = None
    description: str | None = None
    due_day: int | None = None
    currency_id: int | None = None
    amount: Decimal | None = None
    total_installments: int | None = None
    first_due_date: date | None = None
    financing_rate: Decimal | None = None
    overdue_rate: Decimal | None = None
    rates_add_vat: bool | None = None
    shift_weekends: bool | None = None
    is_closed: bool | None = None


class DebtOut(BaseModel):
    id: uuid.UUID
    obligation_type_id: int
    priority_level: int
    institution_id: int | None
    description: str | None
    is_monthly_recurring: bool
    due_day: int | None
    currency_id: int
    amount: Decimal
    total_installments: int | None
    first_due_date: date | None
    financing_rate: Decimal | None
    overdue_rate: Decimal | None
    rates_add_vat: bool
    origin_obligation_id: uuid.UUID | None
    shift_weekends: bool
    is_closed: bool
    review_findings: list[str]
    is_ready: bool

    @classmethod
    def from_model(cls, o: Obligation) -> "DebtOut":
        return cls(
            id=o.id,
            obligation_type_id=o.obligation_type_id,
            priority_level=o.priority_level,
            institution_id=o.institution_id,
            description=o.description,
            is_monthly_recurring=o.is_monthly_recurring,
            due_day=o.due_day,
            currency_id=o.currency_id,
            amount=o.amount,
            total_installments=o.total_installments,
            first_due_date=o.first_due_date,
            financing_rate=o.financing_rate,
            overdue_rate=o.overdue_rate,
            rates_add_vat=o.rates_add_vat,
            origin_obligation_id=o.origin_obligation_id,
            shift_weekends=o.shift_weekends,
            is_closed=o.is_closed,
            review_findings=json.loads(o.review_findings),
            is_ready=o.is_ready,
        )
```

- [ ] **Step 5: Crear el servicio**

`backend/app/services/debt_service.py`:

```python
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.institution import Institution
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.user import User
from app.schemas.debt import DebtCreate, DebtUpdate
from app.services.cash_flow.debts import materialize_debt
from app.services.cash_flow.open_debts import materialize_open_debt
from app.services.review.obligations import review_obligation
from app.services.scoping import require_user_currency

MIN_DESCRIPTION_LENGTH = 8
SYSTEM_PRIORITY_LEVEL = 1
DEBT_KINDS = ("deuda", "deuda_abierta")
SCHEDULE_FIELDS = ("first_due_date", "total_installments", "due_day")


# --- validadores comunes (replicados de expense_service; extracción diferida a post-6c) ---

def _validate_priority(db: Session, priority_level: int | None) -> None:
    if (
        priority_level is None
        or priority_level == SYSTEM_PRIORITY_LEVEL
        or db.get(PriorityLevel, priority_level) is None
    ):
        raise AppError(ErrorCode.priority_level_invalid, field="priority_level")


def _validate_description(description: str | None) -> str:
    cleaned = (description or "").strip()
    if len(cleaned) < MIN_DESCRIPTION_LENGTH:
        raise AppError(ErrorCode.description_invalid, field="description")
    return cleaned


def _validate_amount(amount) -> None:
    if amount is None or amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")


def _validate_due_day(due_day: int | None) -> None:
    if due_day is not None and not (1 <= due_day <= 31):
        raise AppError(ErrorCode.due_day_invalid, field="due_day")


# --- validadores específicos de deudas ---

def _require_debt_type(db: Session, obligation_type_id: int | None) -> ObligationType:
    ot = db.get(ObligationType, obligation_type_id) if obligation_type_id is not None else None
    if ot is None or ot.obligation_kind not in DEBT_KINDS:
        raise AppError(ErrorCode.debt_type_invalid, field="obligation_type_id")
    if ot.obligation_kind == "deuda_abierta" and ot.code != "informal":
        raise AppError(ErrorCode.debt_type_invalid, field="obligation_type_id")
    return ot


def _validate_institution(db: Session, user: User, institution_id: int | None) -> None:
    inst = db.get(Institution, institution_id) if institution_id is not None else None
    if inst is None or inst.country_code != user.country_code:
        raise AppError(ErrorCode.institution_invalid, field="institution_id")


def _validate_rate(rate, field: str) -> None:
    if rate is not None and rate < 0:
        raise AppError(ErrorCode.rates_negative, field=field)


def _validate_deuda_form(due_day, total_installments, first_due_date) -> None:
    if first_due_date is None:
        raise AppError(ErrorCode.debt_requires_schedule_or_date, field="first_due_date")
    if total_installments is not None:  # cronograma
        if total_installments < 1:
            raise AppError(ErrorCode.installments_invalid, field="total_installments")
        if due_day is None:
            raise AppError(ErrorCode.debt_schedule_requires_due_day, field="due_day")
    else:  # pago único
        if due_day is not None:
            raise AppError(ErrorCode.one_time_debt_inconsistent, field="due_day")


def _validate_open_debt_form(due_day, total_installments, first_due_date, financing_rate, overdue_rate) -> None:
    if any(v is not None for v in (due_day, total_installments, first_due_date, financing_rate, overdue_rate)):
        raise AppError(ErrorCode.open_debt_inconsistent)


def _has_payments(db: Session, obligation_id: uuid.UUID) -> bool:
    return db.execute(
        select(CashFlowPayment.id)
        .join(CashFlowEntry, CashFlowEntry.id == CashFlowPayment.cash_flow_entry_id)
        .where(CashFlowEntry.source_type == "deuda", CashFlowEntry.source_id == obligation_id)
        .limit(1)
    ).first() is not None


def _debt_query(user: User):
    return (
        select(Obligation)
        .join(ObligationType, ObligationType.id == Obligation.obligation_type_id)
        .where(Obligation.user_id == user.id, ObligationType.obligation_kind.in_(DEBT_KINDS))
    )


def _run_engines(db: Session, obligation: Obligation, kind: str) -> None:
    review_obligation(db, obligation.id)
    if kind == "deuda":
        materialize_debt(db, obligation.id)
    else:
        materialize_open_debt(db, obligation.id)


def create_debt(db: Session, user: User, payload: DebtCreate) -> Obligation:
    ot = _require_debt_type(db, payload.obligation_type_id)
    kind = ot.obligation_kind
    require_user_currency(db, user, payload.currency_id)
    _validate_priority(db, payload.priority_level)
    description = _validate_description(payload.description)
    _validate_amount(payload.amount)

    if kind == "deuda":
        if payload.institution_id is not None:
            _validate_institution(db, user, payload.institution_id)
        _validate_due_day(payload.due_day)
        _validate_rate(payload.financing_rate, "financing_rate")
        _validate_rate(payload.overdue_rate, "overdue_rate")
        _validate_deuda_form(payload.due_day, payload.total_installments, payload.first_due_date)
        obligation = Obligation(
            user_id=user.id,
            obligation_type_id=payload.obligation_type_id,
            priority_level=payload.priority_level,
            institution_id=payload.institution_id,
            description=description,
            is_monthly_recurring=False,
            due_day=payload.due_day,
            currency_id=payload.currency_id,
            amount=payload.amount,
            total_installments=payload.total_installments,
            first_due_date=payload.first_due_date,
            financing_rate=payload.financing_rate,
            overdue_rate=payload.overdue_rate,
            rates_add_vat=payload.rates_add_vat if payload.rates_add_vat is not None else True,
            shift_weekends=payload.shift_weekends if payload.shift_weekends is not None else False,
            origin_obligation_id=None,
            is_closed=False,
            reviewed_at=None,
            review_findings="[]",
            user_acknowledged_at=None,
            is_ready=False,
        )
    else:  # deuda_abierta: institution_id/rates_add_vat/fechas/cuotas/tasas ignorados o NULL
        _validate_open_debt_form(
            payload.due_day, payload.total_installments, payload.first_due_date,
            payload.financing_rate, payload.overdue_rate,
        )
        obligation = Obligation(
            user_id=user.id,
            obligation_type_id=payload.obligation_type_id,
            priority_level=payload.priority_level,
            institution_id=None,
            description=description,
            is_monthly_recurring=False,
            due_day=None,
            currency_id=payload.currency_id,
            amount=payload.amount,
            total_installments=None,
            first_due_date=None,
            financing_rate=None,
            overdue_rate=None,
            rates_add_vat=False,
            shift_weekends=False,
            origin_obligation_id=None,
            is_closed=False,
            reviewed_at=None,
            review_findings="[]",
            user_acknowledged_at=None,
            is_ready=False,
        )

    db.add(obligation)
    db.flush()
    _run_engines(db, obligation, kind)
    db.commit()
    db.refresh(obligation)
    return obligation


def list_debts(db: Session, user: User) -> list[Obligation]:
    return list(db.execute(_debt_query(user).order_by(Obligation.created_at.desc())).scalars())


def update_debt(db: Session, user: User, obligation_id: uuid.UUID, payload: DebtUpdate) -> Obligation:
    obligation = db.execute(_debt_query(user).where(Obligation.id == obligation_id)).scalar_one_or_none()
    if obligation is None:
        raise AppError(ErrorCode.not_found)
    kind = db.get(ObligationType, obligation.obligation_type_id).obligation_kind

    fields = payload.model_fields_set

    if "obligation_type_id" in fields:
        if kind == "deuda_abierta":
            raise AppError(ErrorCode.debt_type_invalid, field="obligation_type_id")
        new_type = _require_debt_type(db, payload.obligation_type_id)
        if new_type.obligation_kind != kind:
            raise AppError(ErrorCode.debt_type_invalid, field="obligation_type_id")
    if "currency_id" in fields:
        require_user_currency(db, user, payload.currency_id)
    if "priority_level" in fields:
        _validate_priority(db, payload.priority_level)
    if "description" in fields:
        _validate_description(payload.description)
    if "amount" in fields:
        _validate_amount(payload.amount)
    if "institution_id" in fields and payload.institution_id is not None:
        _validate_institution(db, user, payload.institution_id)
    if "due_day" in fields:
        _validate_due_day(payload.due_day)
    if "financing_rate" in fields:
        _validate_rate(payload.financing_rate, "financing_rate")
    if "overdue_rate" in fields:
        _validate_rate(payload.overdue_rate, "overdue_rate")
    for f in ("rates_add_vat", "shift_weekends", "is_closed"):
        if f in fields and getattr(payload, f) is None:
            raise AppError(ErrorCode.field_not_nullable, field=f)

    # bloqueo de cronograma con pagos (solo deuda)
    changing_schedule = any(
        f in fields and getattr(payload, f) != getattr(obligation, f) for f in SCHEDULE_FIELDS
    )
    if changing_schedule and _has_payments(db, obligation.id):
        raise AppError(ErrorCode.debt_schedule_locked)

    # aplicar patch (en deuda_abierta, institution_id y rates_add_vat se ignoran)
    for f in fields:
        if kind == "deuda_abierta" and f in ("institution_id", "rates_add_vat", "obligation_type_id"):
            continue
        value = getattr(payload, f)
        if f == "description":
            value = value.strip()
        setattr(obligation, f, value)

    # consistencia post-merge por kind
    if kind == "deuda":
        _validate_deuda_form(obligation.due_day, obligation.total_installments, obligation.first_due_date)
    else:
        _validate_open_debt_form(
            obligation.due_day, obligation.total_installments, obligation.first_due_date,
            obligation.financing_rate, obligation.overdue_rate,
        )

    db.flush()
    _run_engines(db, obligation, kind)
    db.commit()
    db.refresh(obligation)
    return obligation
```

- [ ] **Step 6: Crear el router**

`backend/app/routers/debts.py`:

```python
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.debt import DebtCreate, DebtOut, DebtUpdate
from app.services import debt_service

router = APIRouter(tags=["debts"])


@router.post("/debts", response_model=DebtOut, status_code=status.HTTP_201_CREATED)
def create_debt(
    payload: DebtCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DebtOut:
    return DebtOut.from_model(debt_service.create_debt(db, user, payload))


@router.get("/debts")
def list_debts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"debts": [DebtOut.from_model(o) for o in debt_service.list_debts(db, user)]}


@router.patch("/debts/{obligation_id}", response_model=DebtOut)
def update_debt(
    obligation_id: uuid.UUID,
    payload: DebtUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DebtOut:
    return DebtOut.from_model(debt_service.update_debt(db, user, obligation_id, payload))
```

- [ ] **Step 7: Registrar el router en `main.py`**

```python
from app.routers import auth, bootstrap, countries, debts, expenses, health, incomes, plan_movements, plans
...
app.include_router(debts.router)
```

- [ ] **Step 8: Correr los tests de POST/GET, verificar verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_debts.py -q
```
Esperado: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/core/errors.py backend/app/schemas/debt.py backend/app/services/debt_service.py backend/app/routers/debts.py backend/app/main.py backend/tests/test_debts.py
git commit -m "feat: endpoints POST/GET debts

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: PATCH debts

**Files:**
- Test: `backend/tests/test_debts.py` (agregar tests de PATCH)

(El servicio `update_debt` y el router ya quedaron escritos en Task 1; esta task agrega sus tests.)

- [ ] **Step 1: Agregar los tests de PATCH**

En `backend/tests/test_debts.py`, agregar:

```python
def _create_cronograma(client, headers):
    return client.post("/debts", json=_cronograma(), headers=headers).json()


def test_patch_cambia_amount(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    resp = client.patch(f"/debts/{d['id']}", json={"amount": "6400.00"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["amount"] == "6400.00"


def test_patch_cambia_tasas_rematerializa(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)  # financing 45, overdue 60 → sin findings
    # bajar financing a 50 (overdue 60 >= 50 → no dispara overdue_lower; tampoco rate_above)
    resp = client.patch(f"/debts/{d['id']}", json={"financing_rate": "50.00"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["financing_rate"] == "50.00"
    assert resp.json()["is_ready"] is True
    # entries futuras con tasa efectiva 50 × 1.22 = 61.00
    assert all(e.financing_rate == Decimal("61.00") for e in _entries(db_session, d["id"]))


def test_patch_cerrar_con_findings_limpia_futuras(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)  # lista, materializó cuotas
    assert len(_entries(db_session, d["id"])) > 0
    # introducir findings: overdue < financing → is_ready false, pero las cuotas siguen
    client.patch(f"/debts/{d['id']}", json={"overdue_rate": "5.00"}, headers=headers)
    # cerrar: reviewer fuerza is_ready=true → motor limpia futuras
    resp = client.patch(f"/debts/{d['id']}", json={"is_closed": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_closed"] is True
    assert resp.json()["review_findings"] == []
    assert resp.json()["is_ready"] is True
    assert _entries(db_session, d["id"]) == []


def test_patch_cronograma_a_pago_unico(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    resp = client.patch(f"/debts/{d['id']}", json={"total_installments": None, "due_day": None},
                       headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total_installments"] is None
    assert resp.json()["due_day"] is None


def test_patch_schedule_locked_con_pagos(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    entry = _entries(db_session, d["id"])[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("6250.00")))  # real
    db_session.flush()
    resp = client.patch(f"/debts/{d['id']}", json={"total_installments": 12}, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "debt_schedule_locked"


def test_patch_amount_no_bloqueado_con_pagos(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    entry = _entries(db_session, d["id"])[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("6250.00")))
    db_session.flush()
    resp = client.patch(f"/debts/{d['id']}", json={"amount": "7000.00"}, headers=headers)
    assert resp.status_code == 200  # amount sí es editable con pagos


def test_patch_tipo_cross_kind_rechazado(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    # 1 es gasto → otro kind
    resp = client.patch(f"/debts/{d['id']}", json={"obligation_type_id": 1}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_type_invalid"


def test_patch_abierta_no_cambia_tipo(client, db_session, catalog):
    headers = _auth(client)
    d = client.post("/debts", json=_abierta(), headers=headers).json()
    resp = client.patch(f"/debts/{d['id']}", json={"obligation_type_id": 9}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "debt_type_invalid"


def test_patch_otro_usuario_404(client, db_session, catalog):
    headers_a = _auth(client, email="a@b.com")
    d = _create_cronograma(client, headers_a)
    headers_b = _auth(client, email="b@b.com")
    resp = client.patch(f"/debts/{d['id']}", json={"amount": "1.00"}, headers=headers_b)
    assert resp.status_code == 404


def test_patch_vacio_ok(client, db_session, catalog):
    headers = _auth(client)
    d = _create_cronograma(client, headers)
    resp = client.patch(f"/debts/{d['id']}", json={}, headers=headers)
    assert resp.status_code == 200
```

- [ ] **Step 2: Correr, verificar verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_debts.py -q
```
Esperado: PASS (POST/GET + PATCH).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_debts.py
git commit -m "test: PATCH debts (incluye debt_schedule_locked y cierre con findings)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Suite completa

- [ ] **Step 1:**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```
Esperado: PASS (todo verde).

---

## Cierre

Tras Task 3 verde: **finishing-a-development-branch** → squash-merge `feat/endpoints-debts` a `main` → push
(manual/prompteado).
