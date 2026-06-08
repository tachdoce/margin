# Endpoints transversales de obligations (6c) — Plan de implementación

> **For agentic workers:** Ejecutar según el modo que elija el usuario (inline o subagente con higiene de
> comandos: `cd` no `git -C`, sin `2>&1`). TDD: test → rojo → implementación → verde → commit por task.

**Goal:** Los 2 endpoints transversales: `DELETE /obligations/{id}` (hard-delete con dos checks) y
`POST /obligations/{id}/acknowledge` (reconocer findings). Cierran el subdominio Obligaciones.

**Architecture:** Router finito `obligations` → `obligation_service` (`delete_obligation`,
`acknowledge_obligation`). DELETE: 2 checks + borrado orquestado. Acknowledge: update de 3 columnas
preservando `updated_at` (patrón `select_plan`) + motor por kind. Response del acknowledge: `DebtOut`
(superset). Error codes nuevos.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pytest. Spec:
`docs/superpowers/specs/2026-06-08-endpoints-obligations-transversales-design.md`.

**Rama:** `feat/endpoints-obligations` → squash-merge a `main`.

---

## Task 0: Crear la rama

- [ ] **Step 1:**

```bash
git checkout -b feat/endpoints-obligations
```

---

## Task 1: Error codes + DELETE + router

**Files:**
- Modify: `backend/app/core/errors.py`
- Create: `backend/app/services/obligation_service.py`
- Create: `backend/app/routers/obligations.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_obligations.py`

- [ ] **Step 1: Agregar error codes**

En `backend/app/core/errors.py`, dentro del enum `ErrorCode` (tras los de debts):

```python
    obligation_has_children = (409, "Borrá primero las obligaciones derivadas de esta.")
    obligation_has_payments = (409, "No se puede borrar una obligación con pagos confirmados.")
    obligation_has_no_findings = (409, "Esta obligación no tiene observaciones para reconocer.")
```

- [ ] **Step 2: Escribir los tests de DELETE (rojo)**

`backend/tests/test_obligations.py`:

```python
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.plan import Plan
from app.models.priority_level import PriorityLevel

FUTURE = (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture
def catalog(db_session, seed_uy_currency):
    db_session.add_all([
        PriorityLevel(level=3, name="Crítica", description="x"),
        PriorityLevel(level=4, name="Prioritaria", description="x"),
        PriorityLevel(level=5, name="Manejable", description="x"),
    ])
    db_session.flush()
    db_session.add_all([
        ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                       description="x", default_priority_level=3, visible=True),
        ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                       description="x", default_priority_level=5, visible=True),
        ObligationType(id=8, obligation_kind="deuda_abierta", code="informal", name="Informal",
                       description="x", default_priority_level=3, visible=True),
    ])
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _crear_gasto(client, headers):
    body = {
        "obligation_type_id": 1, "priority_level": 3, "description": "Alquiler depto",
        "is_monthly_recurring": True, "due_day": 10, "currency_id": 1, "amount": "32000.00",
    }
    return client.post("/expenses", json=body, headers=headers).json()


def _crear_abierta(client, headers):
    body = {
        "obligation_type_id": 8, "priority_level": 3, "description": "Le debo a mi viejo",
        "currency_id": 1, "amount": "50000.00",
    }
    return client.post("/debts", json=body, headers=headers).json()


def _crear_deuda_con_findings(client, headers):
    # overdue < financing → finding overdue_lower_than_financing → is_ready false, sin entries
    body = {
        "obligation_type_id": 10, "priority_level": 5, "description": "Préstamo tasas raras",
        "due_day": 10, "currency_id": 1, "amount": "6250.00", "total_installments": 24,
        "first_due_date": FUTURE, "financing_rate": "45.00", "overdue_rate": "30.00",
    }
    return client.post("/debts", json=body, headers=headers).json()


def _obligation(db_session, obligation_id):
    return db_session.get(Obligation, obligation_id)


def _entries(db_session, obligation_id):
    return list(db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_id == obligation_id)
    ).scalars())


# --- DELETE ---

def test_delete_gasto_ok(client, db_session, catalog):
    headers = _auth(client)
    g = _crear_gasto(client, headers)
    assert len(_entries(db_session, g["id"])) > 0
    resp = client.delete(f"/obligations/{g['id']}", headers=headers)
    assert resp.status_code == 204
    assert _obligation(db_session, g["id"]) is None
    assert _entries(db_session, g["id"]) == []


def test_delete_abierta_ok(client, db_session, catalog):
    headers = _auth(client)
    d = _crear_abierta(client, headers)
    resp = client.delete(f"/obligations/{d['id']}", headers=headers)
    assert resp.status_code == 204
    assert _obligation(db_session, d["id"]) is None


def test_delete_not_found(client, db_session, catalog):
    headers = _auth(client)
    import uuid
    resp = client.delete(f"/obligations/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


def test_delete_otro_usuario_404(client, db_session, catalog):
    headers_a = _auth(client, email="a@b.com")
    g = _crear_gasto(client, headers_a)
    headers_b = _auth(client, email="b@b.com")
    resp = client.delete(f"/obligations/{g['id']}", headers=headers_b)
    assert resp.status_code == 404


def test_delete_con_hija(client, db_session, catalog):
    headers = _auth(client)
    parent = _crear_gasto(client, headers)
    user_id = _obligation(db_session, parent["id"]).user_id
    child = Obligation(
        user_id=user_id, obligation_type_id=10, priority_level=5, currency_id=1,
        amount=Decimal("100.00"), is_monthly_recurring=False, shift_weekends=False,
        rates_add_vat=True, is_closed=False, review_findings="[]", is_ready=False,
        origin_obligation_id=parent["id"],
    )
    db_session.add(child)
    db_session.flush()
    resp = client.delete(f"/obligations/{parent['id']}", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "obligation_has_children"


def test_delete_con_pago_real(client, db_session, catalog):
    headers = _auth(client)
    g = _crear_gasto(client, headers)
    entry = _entries(db_session, g["id"])[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("32000.00")))  # plan_id None
    db_session.flush()
    resp = client.delete(f"/obligations/{g['id']}", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "obligation_has_payments"


def test_delete_con_pago_planificado_ok(client, db_session, catalog):
    headers = _auth(client)
    g = _crear_gasto(client, headers)
    entry = _entries(db_session, g["id"])[0]
    plan = Plan(user_id=_obligation(db_session, g["id"]).user_id, name="P", is_default=False,
                is_engine_generated=False, selected_at=datetime.now(timezone.utc), dial_amount=Decimal("0"),
                dial_currency_id=1, goal_kind=None, goal_amount=None, goal_currency_id=None)
    db_session.add(plan)
    db_session.flush()
    db_session.add(CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("100.00"), plan_id=plan.id))
    db_session.flush()
    resp = client.delete(f"/obligations/{g['id']}", headers=headers)
    assert resp.status_code == 204
    assert _obligation(db_session, g["id"]) is None


def test_delete_sin_token(client, db_session, catalog):
    import uuid
    assert client.delete(f"/obligations/{uuid.uuid4()}").status_code == 401
```

- [ ] **Step 3: Correr, verificar que fallan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_obligations.py -q
```
Esperado: FAIL.

- [ ] **Step 4: Crear el servicio (delete)**

`backend/app/services/obligation_service.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.user import User
from app.services.cash_flow.debts import materialize_debt
from app.services.cash_flow.expenses import materialize_expense
from app.services.cash_flow.open_debts import materialize_open_debt

OBLIGATION_SOURCE_TYPES = ("gasto", "deuda", "deuda_abierta")


def _get_owned(db: Session, user: User, obligation_id: uuid.UUID) -> Obligation:
    obligation = db.execute(
        select(Obligation).where(Obligation.id == obligation_id, Obligation.user_id == user.id)
    ).scalar_one_or_none()
    if obligation is None:
        raise AppError(ErrorCode.not_found)
    return obligation


def delete_obligation(db: Session, user: User, obligation_id: uuid.UUID) -> None:
    obligation = _get_owned(db, user, obligation_id)

    # check (a): sin hijas
    has_children = db.execute(
        select(Obligation.id).where(Obligation.origin_obligation_id == obligation.id).limit(1)
    ).first() is not None
    if has_children:
        raise AppError(ErrorCode.obligation_has_children)

    # check (b): sin pagos reales (plan_id IS NULL)
    has_real_payments = db.execute(
        select(CashFlowPayment.id)
        .join(CashFlowEntry, CashFlowEntry.id == CashFlowPayment.cash_flow_entry_id)
        .where(
            CashFlowEntry.source_type.in_(OBLIGATION_SOURCE_TYPES),
            CashFlowEntry.source_id == obligation.id,
            CashFlowPayment.plan_id.is_(None),
        )
        .limit(1)
    ).first() is not None
    if has_real_payments:
        raise AppError(ErrorCode.obligation_has_payments)

    # borrado orquestado: entries (sus pagos planificados caen por cascade) → la obligación
    db.execute(
        delete(CashFlowEntry).where(
            CashFlowEntry.source_type.in_(OBLIGATION_SOURCE_TYPES),
            CashFlowEntry.source_id == obligation.id,
        )
    )
    db.delete(obligation)
    db.commit()


def acknowledge_obligation(db: Session, user: User, obligation_id: uuid.UUID) -> Obligation:
    obligation = _get_owned(db, user, obligation_id)
    if obligation.review_findings == "[]":
        raise AppError(ErrorCode.obligation_has_no_findings)

    # update de 3 columnas; updated_at se preserva (reconocer no es cambio de negocio)
    db.execute(
        update(Obligation)
        .where(Obligation.id == obligation.id)
        .values(
            review_findings="[]",
            user_acknowledged_at=datetime.now(timezone.utc),
            is_ready=True,
            updated_at=obligation.updated_at,
        )
    )
    db.refresh(obligation)  # sincroniza el objeto (is_ready=true) antes de invocar el motor

    kind = db.get(ObligationType, obligation.obligation_type_id).obligation_kind
    if kind == "gasto":
        materialize_expense(db, obligation.id)
    elif kind == "deuda":
        materialize_debt(db, obligation.id)
    else:
        materialize_open_debt(db, obligation.id)

    db.commit()
    db.refresh(obligation)
    return obligation
```

- [ ] **Step 5: Crear el router**

`backend/app/routers/obligations.py`:

```python
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.debt import DebtOut
from app.services import obligation_service

router = APIRouter(tags=["obligations"])


@router.delete("/obligations/{obligation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_obligation(
    obligation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    obligation_service.delete_obligation(db, user, obligation_id)


@router.post("/obligations/{obligation_id}/acknowledge", response_model=DebtOut)
def acknowledge_obligation(
    obligation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DebtOut:
    return DebtOut.from_model(obligation_service.acknowledge_obligation(db, user, obligation_id))
```

- [ ] **Step 6: Registrar el router en `main.py`**

```python
from app.routers import (auth, bootstrap, countries, debts, expenses, health, incomes,
                         obligations, plan_movements, plans)
...
app.include_router(obligations.router)
```

- [ ] **Step 7: Correr los tests de DELETE, verificar verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_obligations.py -q
```
Esperado: PASS (los de DELETE; los de acknowledge se agregan en Task 2).

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/errors.py backend/app/services/obligation_service.py backend/app/routers/obligations.py backend/app/main.py backend/tests/test_obligations.py
git commit -m "feat: DELETE /obligations/{id} (hard-delete con dos checks)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: POST acknowledge (tests)

**Files:**
- Test: `backend/tests/test_obligations.py` (agregar tests de acknowledge)

(El servicio `acknowledge_obligation` y el router ya quedaron escritos en Task 1; esta task agrega sus tests.)

- [ ] **Step 1: Agregar los tests de acknowledge**

En `backend/tests/test_obligations.py`, agregar:

```python
def test_acknowledge_materializa_lo_frenado(client, db_session, catalog):
    headers = _auth(client)
    d = _crear_deuda_con_findings(client, headers)
    assert d["is_ready"] is False
    assert d["review_findings"] == ["overdue_lower_than_financing"]
    assert _entries(db_session, d["id"]) == []  # findings frenaron al motor
    updated_before = _obligation(db_session, d["id"]).updated_at
    resp = client.post(f"/obligations/{d['id']}/acknowledge", json={}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_findings"] == []
    assert body["is_ready"] is True
    assert len(_entries(db_session, d["id"])) > 0  # ahora sí materializó
    # updated_at no cambió (reconocer no es cambio de negocio)
    assert _obligation(db_session, d["id"]).updated_at == updated_before


def test_acknowledge_sin_findings_409(client, db_session, catalog):
    headers = _auth(client)
    g = _crear_gasto(client, headers)  # gasto sin tasas → is_ready true, review_findings []
    resp = client.post(f"/obligations/{g['id']}/acknowledge", json={}, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "obligation_has_no_findings"


def test_acknowledge_not_found(client, db_session, catalog):
    headers = _auth(client)
    import uuid
    resp = client.post(f"/obligations/{uuid.uuid4()}/acknowledge", json={}, headers=headers)
    assert resp.status_code == 404


def test_acknowledge_otro_usuario_404(client, db_session, catalog):
    headers_a = _auth(client, email="a@b.com")
    d = _crear_deuda_con_findings(client, headers_a)
    headers_b = _auth(client, email="b@b.com")
    resp = client.post(f"/obligations/{d['id']}/acknowledge", json={}, headers=headers_b)
    assert resp.status_code == 404


def test_acknowledge_sin_token(client, db_session, catalog):
    import uuid
    assert client.post(f"/obligations/{uuid.uuid4()}/acknowledge", json={}).status_code == 401
```

- [ ] **Step 2: Correr, verificar verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_obligations.py -q
```
Esperado: PASS (DELETE + acknowledge).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_obligations.py
git commit -m "test: POST /obligations/{id}/acknowledge

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

Tras Task 3 verde: **finishing-a-development-branch** → squash-merge `feat/endpoints-obligations` a `main` →
push (manual/prompteado). **Con esto queda cerrado el subdominio Obligaciones completo.**
