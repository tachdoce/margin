# `GET` + `DELETE` + `reactivate` /incomes (slice 3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar `GET /incomes` (lista todo con `is_deleted`), `DELETE /incomes/{id}` (soft-delete provisorio, 204) y `POST /incomes/{id}/reactivate` (limpia `deleted_at`, 200), sumándolos al router/servicio de incomes existentes.

**Architecture:** Router finito → `income_service` (lanza `AppError`) → modelo `Income`. El DELETE es soft incondicional (provisorio; se reemplaza por el híbrido real con el CashFlowEngine). Respuestas vía `IncomeOut.from_model` y un `IncomeListOut` nuevo.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, pytest. Python 3.13 (`backend/.venv`).

**Spec:** `docs/superpowers/specs/2026-06-07-incomes-get-delete-reactivate-design.md`.

**Git:** rama `feat/incomes-get-delete-reactivate`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/
├── core/errors.py            # + income_not_deleted (409)   (MODIFICAR)
├── schemas/income.py         # + IncomeListOut   (MODIFICAR)
├── services/income_service.py # + list_incomes / delete_income / reactivate_income   (MODIFICAR)
└── routers/incomes.py        # + GET / DELETE / POST reactivate   (MODIFICAR)
backend/tests/
└── test_incomes.py           # + tests de GET / DELETE / reactivate   (MODIFICAR)
```

---

## Task 1: Prerrequisitos — error code + `IncomeListOut`

**Files:** Modify `backend/app/core/errors.py`, `backend/app/schemas/income.py`

- [ ] **Step 1: Agregar el error code en `backend/app/core/errors.py`**

Después de la línea `field_not_nullable = (422, "Ese campo no puede ser nulo.")`, agregar:

```python
    income_not_deleted = (409, "Este ingreso no está borrado.")
```

- [ ] **Step 2: Agregar `IncomeListOut` en `backend/app/schemas/income.py`**

Al final del archivo:

```python
class IncomeListOut(BaseModel):
    incomes: list[IncomeOut]
```

- [ ] **Step 3: Verificar imports**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && python -c "from app.core.errors import ErrorCode; from app.schemas.income import IncomeListOut; print(ErrorCode.income_not_deleted.status_code)"`
Expected: `409`

- [ ] **Step 4: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/core/errors.py backend/app/schemas/income.py
git commit -m "feat(backend): income_not_deleted + schema IncomeListOut"
```

---

## Task 2: `GET /incomes` — servicio + router + tests (TDD)

**Files:** Modify `backend/app/services/income_service.py`, `backend/app/routers/incomes.py`, `backend/tests/test_incomes.py`

- [ ] **Step 1: Agregar los imports necesarios al inicio de `backend/tests/test_incomes.py`**

Debajo de los imports existentes (que ya incluyen `from decimal import Decimal`, `from sqlalchemy import select`, los modelos `Country/Currency/Income/IncomeType`), agregar:

```python
from datetime import datetime, timezone

from app.core.security import create_access_token
from app.models.user import User
```

- [ ] **Step 2: Agregar los tests de GET al final de `backend/tests/test_incomes.py`**

```python
def test_get_empty(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.get("/incomes", headers=_auth(client))
    assert resp.status_code == 200
    assert resp.json() == {"incomes": []}


def test_get_requires_auth(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.get("/incomes")
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_get_orders_by_created_desc(client, db_session, seed_uy):
    _seed_refs(db_session)
    user = User(country_code="UY", display_name="T")
    db_session.add(user)
    db_session.flush()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    # En el test todo corre en una transacción, así que now() sería igual para ambos:
    # forzamos created_at distintos para probar el orden.
    db_session.add(Income(
        user_id=user.id, income_type_id=1, currency_id=1, amount=Decimal("1.00"),
        description="ingreso viejo", is_monthly_recurring=True, payment_day=1, shift_weekends=False,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    db_session.add(Income(
        user_id=user.id, income_type_id=1, currency_id=1, amount=Decimal("2.00"),
        description="ingreso nuevo", is_monthly_recurring=True, payment_day=1, shift_weekends=False,
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    ))
    db_session.flush()
    resp = client.get("/incomes", headers=headers)
    assert resp.status_code == 200
    descriptions = [i["description"] for i in resp.json()["incomes"]]
    assert descriptions == ["ingreso nuevo", "ingreso viejo"]  # más nuevo primero


def test_get_only_own_incomes(client, db_session, seed_uy):
    _seed_refs(db_session)
    owner = _auth(client, email="owner@b.com")
    _create_recurring(client, owner)
    other = _auth(client, email="other@b.com")
    resp = client.get("/incomes", headers=other)
    assert resp.status_code == 200
    assert resp.json()["incomes"] == []
```

- [ ] **Step 3: Correr y verificar que fallan**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_incomes.py -q`
Expected: FALLAN los de GET (el endpoint no existe → 404/405).

- [ ] **Step 4: Agregar `list_incomes` al servicio `backend/app/services/income_service.py`**

Al final del archivo:

```python
def list_incomes(db: Session, user: User) -> list[Income]:
    return list(
        db.execute(
            select(Income).where(Income.user_id == user.id).order_by(Income.created_at.desc())
        ).scalars()
    )
```

- [ ] **Step 5: Agregar el endpoint GET al router `backend/app/routers/incomes.py`**

Cambiar el import de schemas para incluir `IncomeListOut`:

```python
from app.schemas.income import IncomeCreate, IncomeListOut, IncomeOut, IncomeUpdate
```

Y agregar al final del archivo:

```python
@router.get("/incomes", response_model=IncomeListOut)
def list_incomes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeListOut:
    incomes = income_service.list_incomes(db, user)
    return IncomeListOut(incomes=[IncomeOut.from_model(i) for i in incomes])
```

- [ ] **Step 6: Correr y verificar que pasan**

Run: `pytest tests/test_incomes.py -q`
Expected: PASAN todos (los previos + los de GET).

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/income_service.py backend/app/routers/incomes.py backend/tests/test_incomes.py
git commit -m "feat(backend): GET /incomes (lista del usuario con is_deleted)"
```

---

## Task 3: `DELETE /incomes/{id}` — soft-delete provisorio + tests (TDD)

**Files:** Modify `backend/app/services/income_service.py`, `backend/app/routers/incomes.py`, `backend/tests/test_incomes.py`

- [ ] **Step 1: Agregar los tests de DELETE al final de `backend/tests/test_incomes.py`**

```python
def test_delete_soft_deletes(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.delete(f"/incomes/{income['id']}", headers=headers)
    assert resp.status_code == 204
    # sigue apareciendo en GET, ahora con is_deleted=true
    listed = client.get("/incomes", headers=headers).json()["incomes"]
    assert len(listed) == 1
    assert listed[0]["id"] == income["id"]
    assert listed[0]["is_deleted"] is True


def test_delete_twice_not_found(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    assert client.delete(f"/incomes/{income['id']}", headers=headers).status_code == 204
    resp = client.delete(f"/incomes/{income['id']}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_delete_other_users_income_not_found(client, db_session, seed_uy):
    _seed_refs(db_session)
    owner = _auth(client, email="owner@b.com")
    income = _create_recurring(client, owner)
    other = _auth(client, email="other@b.com")
    resp = client.delete(f"/incomes/{income['id']}", headers=other)
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_delete_missing_not_found(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    resp = client.delete("/incomes/00000000-0000-0000-0000-000000000000", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_delete_requires_auth(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.delete("/incomes/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_incomes.py -q`
Expected: FALLAN los de DELETE (el endpoint no existe → 404/405).

- [ ] **Step 3: Agregar el import de `datetime` al servicio y `delete_income`**

En `backend/app/services/income_service.py`, agregar arriba (después de `import uuid`):

```python
from datetime import datetime, timezone
```

Y agregar al final del archivo:

```python
def delete_income(db: Session, user: User, income_id: uuid.UUID) -> None:
    """Soft-delete provisorio: setea deleted_at. (El DELETE híbrido real llega con el CashFlowEngine.)"""
    income = db.execute(
        select(Income).where(
            Income.id == income_id,
            Income.user_id == user.id,
            Income.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if income is None:
        raise AppError(ErrorCode.not_found)
    income.deleted_at = datetime.now(timezone.utc)
    db.commit()
```

- [ ] **Step 4: Agregar el endpoint DELETE al router `backend/app/routers/incomes.py`**

Al final del archivo:

```python
@router.delete("/incomes/{income_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_income(
    income_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    income_service.delete_income(db, user, income_id)
```

- [ ] **Step 5: Correr y verificar que pasan**

Run: `pytest tests/test_incomes.py -q`
Expected: PASAN todos.

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/income_service.py backend/app/routers/incomes.py backend/tests/test_incomes.py
git commit -m "feat(backend): DELETE /incomes/{id} (soft-delete provisorio, 204)"
```

---

## Task 4: `POST /incomes/{id}/reactivate` + tests (TDD)

**Files:** Modify `backend/app/services/income_service.py`, `backend/app/routers/incomes.py`, `backend/tests/test_incomes.py`

- [ ] **Step 1: Agregar los tests de reactivate al final de `backend/tests/test_incomes.py`**

```python
def test_reactivate_revives(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    client.delete(f"/incomes/{income['id']}", headers=headers)
    resp = client.post(f"/incomes/{income['id']}/reactivate", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_deleted"] is False
    # en GET vuelve como vigente
    listed = client.get("/incomes", headers=headers).json()["incomes"]
    assert listed[0]["is_deleted"] is False


def test_reactivate_not_deleted_conflict(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)  # vigente, nunca borrada
    resp = client.post(f"/incomes/{income['id']}/reactivate", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "income_not_deleted"


def test_reactivate_other_users_income_not_found(client, db_session, seed_uy):
    _seed_refs(db_session)
    owner = _auth(client, email="owner@b.com")
    income = _create_recurring(client, owner)
    client.delete(f"/incomes/{income['id']}", headers=owner)
    other = _auth(client, email="other@b.com")
    resp = client.post(f"/incomes/{income['id']}/reactivate", headers=other)
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_reactivate_missing_not_found(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    resp = client.post("/incomes/00000000-0000-0000-0000-000000000000/reactivate", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_reactivate_requires_auth(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes/00000000-0000-0000-0000-000000000000/reactivate")
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_incomes.py -q`
Expected: FALLAN los de reactivate (el endpoint no existe → 404 con detalle de FastAPI o 405).

- [ ] **Step 3: Agregar `reactivate_income` al servicio `backend/app/services/income_service.py`**

Al final del archivo:

```python
def reactivate_income(db: Session, user: User, income_id: uuid.UUID) -> Income:
    income = db.execute(
        select(Income).where(
            Income.id == income_id,
            Income.user_id == user.id,
        )
    ).scalar_one_or_none()
    if income is None:
        raise AppError(ErrorCode.not_found)
    if income.deleted_at is None:
        raise AppError(ErrorCode.income_not_deleted)
    income.deleted_at = None
    db.commit()
    db.refresh(income)
    return income
```

- [ ] **Step 4: Agregar el endpoint reactivate al router `backend/app/routers/incomes.py`**

Al final del archivo:

```python
@router.post("/incomes/{income_id}/reactivate", response_model=IncomeOut)
def reactivate_income(
    income_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeOut:
    income = income_service.reactivate_income(db, user, income_id)
    return IncomeOut.from_model(income)
```

- [ ] **Step 5: Correr y verificar que pasan los de incomes**

Run: `pytest tests/test_incomes.py -q`
Expected: PASAN todos.

- [ ] **Step 6: Regresión de la suite completa**

Run: `pytest -q`
Expected: pasan todos.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/income_service.py backend/app/routers/incomes.py backend/tests/test_incomes.py
git commit -m "feat(backend): POST /incomes/{id}/reactivate"
```

---

## Notas de cierre

- Al terminar: `GET /incomes`, `DELETE /incomes/{id}` (soft) y `POST /incomes/{id}/reactivate` andando. Con esto la primera tanda de Ingresos (slices 1–3) queda completa salvo lo diferido al CashFlowEngine.
- **Cierre:** squash-merge de `feat/incomes-get-delete-reactivate` → un commit `feat: GET + DELETE + reactivate incomes` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** GET lista todo del usuario ordenado por created_at desc con is_deleted (§2) — Task 2 (`list_incomes` + router + test de orden/aislamiento) ✓; DELETE soft provisorio 204 + 404 (§2) — Task 3 ✓; reactivate 200/404/409 (§2) — Task 4 ✓; `IncomeListOut` (§3) — Task 1 ✓; `income_not_deleted` 409 (§6) — Task 1 ✓; servicio con 3 funciones (§4) — Tasks 2/3/4 ✓; router con 3 endpoints (§5) — Tasks 2/3/4 ✓; testing (§7) — Tasks 2/3/4 ✓.
- **Placeholders:** ninguno; código completo en cada paso.
- **Consistencia de tipos:** `list_incomes(db, user) -> list[Income]`, `delete_income(db, user, income_id) -> None`, `reactivate_income(db, user, income_id) -> Income` consistentes entre servicio, router y plan; `IncomeListOut(incomes=list[IncomeOut])` usado igual en schema y router; `IncomeOut.from_model` reusado; el test de orden crea filas con `created_at` explícito porque en una sola transacción `now()` es constante (evita un test no determinista).
```
