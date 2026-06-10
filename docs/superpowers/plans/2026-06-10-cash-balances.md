# cash_balances — efectivo del usuario — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Tabla `cash_balances` (snapshot del efectivo por moneda) + `GET /cash-balances` (derivado, 1 entrada
por moneda holdable) + `PUT /cash-balances` (upsert masivo atómico).

**Architecture:** Tabla con PK compuesta `(user_id, currency_id)`. Las monedas "holdable" del usuario =
`currencies` del país con `allowed_in_credit_card=true`. El GET deriva la lista (catálogo ∪ filas, 0.00 default);
el PUT valida todo el body y luego upsertea, atómico.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-cash-balances-design.md`

**Branch:** `feat/cash-balances` (NO trabajar en `main`). Squash-merge al final. **No tocar Notion.**

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

**Patrones del repo (verificados):**
- PK compuesta sin `id`: dos `mapped_column(..., primary_key=True)` (ver `currency_rate.py`).
- `db.get(Modelo, (pk1, pk2))` con tupla en el orden de las PK.
- `scoping.py` tiene `require_country_scoped`/`require_user_currency`. `currency_not_available` ya existe.
- Pydantic v2 serializa `Decimal` como string. Tests sobre `margin_test` (`create_all` + savepoint). Fixture
  `seed_uy_currency` siembra Peso id 1; el resto de monedas se siembran en el test.
- **Tras agregar la tabla, recordá que `create_all` no altera tablas existentes**: si la suite falla por schema
  viejo en `margin_test`, recrear el schema (drop_all + create_all desde los modelos) — pero una tabla **nueva**
  la crea `create_all` sin problema, así que normalmente no hace falta.

---

## File Structure

| Archivo | Cambio |
|---|---|
| `app/models/cash_balance.py` | modelo `CashBalance` (PK compuesta) |
| `app/models/__init__.py` | registrar `CashBalance` |
| `alembic/versions/<rev>_create_cash_balances.py` | crea la tabla (autogenerate + verificación) |
| `app/services/scoping.py` | + `holdable_currencies`, `require_holdable_currency` |
| `app/core/errors.py` | + `amount_negative`, `duplicate_currency` |
| `app/schemas/cash_balance.py` | `CashBalanceOut`, `CashBalanceSetItem`, `CashBalancesSet` |
| `app/services/cash_balance_service.py` | `get_balances`, `set_balances` |
| `app/routers/cash_balances.py` | GET + PUT; registrar en `main.py` |
| `tests/test_cash_balances.py` | GET + PUT |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/cash-balances
```

---

## Task 1: Modelo + migración

**Files:** `app/models/cash_balance.py`, `app/models/__init__.py`,
`alembic/versions/<rev>_create_cash_balances.py`, `tests/test_cash_balances.py`

- [ ] **Step 1: Test del modelo (rojo)** — crear `tests/test_cash_balances.py`:

```python
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_balance import CashBalance
from app.models.user import User


def _user(db_session, client):
    client.post("/auth/register", json={"email": "u@b.com", "password": "12345678"})
    return db_session.execute(select(User).order_by(User.created_at.desc())).scalars().all()[-1]


def test_insert_cash_balance(client, db_session, seed_uy_currency):
    user = _user(db_session, client)
    db_session.add(CashBalance(user_id=user.id, currency_id=1, amount=Decimal("15000.00")))
    db_session.commit()
    row = db_session.get(CashBalance, (user.id, 1))
    assert row.amount == Decimal("15000.00")
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_balances.py -q
```

Expected: FALLA (`ModuleNotFoundError: app.models.cash_balance`).

- [ ] **Step 3: Modelo** `app/models/cash_balance.py`:

```python
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CashBalance(Base):
    __tablename__ = "cash_balances"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    currency_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("currencies.id"), primary_key=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Registrar el modelo** en `app/models/__init__.py` (agregar `from app.models.cash_balance import
  CashBalance` siguiendo el patrón de los demás, y sumarlo a `__all__` si existe).

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_balances.py -q
```

- [ ] **Step 6: Migración (autogenerate + verificación).**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic upgrade head && alembic revision --autogenerate -m "create cash_balances"
```

Abrir el archivo generado y verificar: `upgrade()` crea `cash_balances` con PK compuesta
`(user_id, currency_id)` y las FKs; `downgrade()` hace `op.drop_table('cash_balances')`. Sin cambios espurios.
Aplicar:

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic upgrade head
```

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/cash_balance.py app/models/__init__.py alembic/versions/ tests/test_cash_balances.py && git commit -m "feat: tabla cash_balances (modelo + migración)"
```

---

## Task 2: scoping + codes + schemas + GET

**Files:** `app/services/scoping.py`, `app/core/errors.py`, `app/schemas/cash_balance.py`,
`app/services/cash_balance_service.py`, `app/routers/cash_balances.py`, `app/main.py`,
`tests/test_cash_balances.py`

- [ ] **Step 1: Helpers en `scoping.py`** (al final del módulo):

```python
def holdable_currencies(db: Session, user: User) -> list[Currency]:
    """Monedas que el usuario puede tener como efectivo: de su país y allowed_in_credit_card."""
    return list(
        db.execute(
            select(Currency)
            .where(Currency.country_code == user.country_code, Currency.allowed_in_credit_card.is_(True))
            .order_by(Currency.id)
        ).scalars()
    )


def require_holdable_currency(db: Session, user: User, currency_id: int | None) -> Currency:
    cur = db.get(Currency, currency_id) if currency_id is not None else None
    if cur is None or cur.country_code != user.country_code or not cur.allowed_in_credit_card:
        raise AppError(ErrorCode.currency_not_available, field="currency_id")
    return cur
```

- [ ] **Step 2: Codes** en `app/core/errors.py` (dentro de `ErrorCode`):

```python
    amount_negative = (422, "El monto no puede ser negativo.")
    duplicate_currency = (422, "No repitas la misma moneda.")
```

- [ ] **Step 3: Schemas** `app/schemas/cash_balance.py`:

```python
from decimal import Decimal

from pydantic import BaseModel


class CashBalanceOut(BaseModel):
    currency_id: int
    amount: Decimal


class CashBalanceSetItem(BaseModel):
    currency_id: int
    amount: Decimal


class CashBalancesSet(BaseModel):
    balances: list[CashBalanceSetItem]
```

- [ ] **Step 4: Service** `app/services/cash_balance_service.py` (por ahora `get_balances`):

```python
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_balance import CashBalance
from app.models.user import User
from app.schemas.cash_balance import CashBalanceOut
from app.services.scoping import holdable_currencies


def get_balances(db: Session, user: User) -> list[CashBalanceOut]:
    stored = {
        b.currency_id: b.amount
        for b in db.execute(select(CashBalance).where(CashBalance.user_id == user.id)).scalars()
    }
    return [
        CashBalanceOut(currency_id=c.id, amount=stored.get(c.id, Decimal("0.00")))
        for c in holdable_currencies(db, user)
    ]
```

- [ ] **Step 5: Router** `app/routers/cash_balances.py` (por ahora GET):

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.cash_balance import CashBalanceOut
from app.services import cash_balance_service as svc

router = APIRouter(tags=["cash-balances"])


@router.get("/cash-balances", response_model=list[CashBalanceOut])
def list_balances(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CashBalanceOut]:
    return svc.get_balances(db, user)
```

- [ ] **Step 6: Registrar el router** en `app/main.py` (import + `app.include_router(cash_balances.router)`).

- [ ] **Step 7: Tests del GET** — agregar a `tests/test_cash_balances.py` (helper de monedas + auth):

```python
from app.models.currency import Currency


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_currencies(db_session):
    # seed_uy_currency ya sembró Peso(1, holdable). Sumar Dólar(3, holdable) y UI(4, NO holdable).
    db_session.add(Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True))
    db_session.add(Currency(id=4, country_code="UY", name="Unidad Indexada", is_legal_tender=False, allowed_in_credit_card=False))
    db_session.commit()


def test_get_lists_holdable_zero_default(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    rows = client.get("/cash-balances", headers=headers).json()
    assert rows == [{"currency_id": 1, "amount": "0.00"}, {"currency_id": 3, "amount": "0.00"}]  # sin UI(4)


def test_get_requires_auth(client, db_session, seed_uy_currency):
    assert client.get("/cash-balances").status_code == 401
```

- [ ] **Step 8: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_balances.py -q
```

- [ ] **Step 9: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/scoping.py app/core/errors.py app/schemas/cash_balance.py app/services/cash_balance_service.py app/routers/cash_balances.py app/main.py tests/test_cash_balances.py && git commit -m "feat: GET /cash-balances"
```

---

## Task 3: PUT masivo (upsert atómico)

**Files:** `app/services/cash_balance_service.py`, `app/routers/cash_balances.py`, `tests/test_cash_balances.py`

- [ ] **Step 1: Service `set_balances`** — agregar a `cash_balance_service.py` (imports: `AppError`,
  `ErrorCode`, `CashBalance`, `CashBalancesSet`, `require_holdable_currency`):

```python
def set_balances(db: Session, user: User, payload: CashBalancesSet) -> list[CashBalanceOut]:
    # validar TODO el body antes de escribir (atómico)
    seen: set[int] = set()
    for item in payload.balances:
        if item.currency_id in seen:
            raise AppError(ErrorCode.duplicate_currency, field="currency_id")
        seen.add(item.currency_id)
        require_holdable_currency(db, user, item.currency_id)  # 422 currency_not_available
        if item.amount < 0:
            raise AppError(ErrorCode.amount_negative, field="amount")

    for item in payload.balances:
        row = db.get(CashBalance, (user.id, item.currency_id))
        if row is None:
            db.add(CashBalance(user_id=user.id, currency_id=item.currency_id, amount=item.amount))
        else:
            row.amount = item.amount
    db.flush()
    db.commit()
    return get_balances(db, user)
```

Agregar los imports nuevos al tope del service:

```python
from app.core.errors import AppError, ErrorCode
from app.schemas.cash_balance import CashBalanceOut, CashBalancesSet
from app.services.scoping import holdable_currencies, require_holdable_currency
```

- [ ] **Step 2: Ruta PUT en el router**:

```python
from app.schemas.cash_balance import CashBalanceOut, CashBalancesSet
```
```python
@router.put("/cash-balances", response_model=list[CashBalanceOut])
def set_balances(
    payload: CashBalancesSet,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CashBalanceOut]:
    return svc.set_balances(db, user, payload)
```

- [ ] **Step 3: Tests del PUT** — agregar a `tests/test_cash_balances.py`:

```python
def test_put_sets_multiple_atomic(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    body = {"balances": [{"currency_id": 1, "amount": "15000.00"}, {"currency_id": 3, "amount": "200.00"}]}
    r = client.put("/cash-balances", json=body, headers=headers)
    assert r.status_code == 200
    assert r.json() == [{"currency_id": 1, "amount": "15000.00"}, {"currency_id": 3, "amount": "200.00"}]


def test_put_upsert_updates(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    client.put("/cash-balances", json={"balances": [{"currency_id": 1, "amount": "100.00"}]}, headers=headers)
    client.put("/cash-balances", json={"balances": [{"currency_id": 1, "amount": "500.00"}]}, headers=headers)
    rows = client.get("/cash-balances", headers=headers).json()
    assert next(x for x in rows if x["currency_id"] == 1)["amount"] == "500.00"


def test_put_non_holdable(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    r = client.put("/cash-balances", json={"balances": [{"currency_id": 4, "amount": "10.00"}]}, headers=headers)
    assert r.json()["code"] == "currency_not_available"


def test_put_negative(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    r = client.put("/cash-balances", json={"balances": [{"currency_id": 1, "amount": "-5.00"}]}, headers=headers)
    assert r.json()["code"] == "amount_negative"


def test_put_zero_ok(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    r = client.put("/cash-balances", json={"balances": [{"currency_id": 1, "amount": "0"}]}, headers=headers)
    assert r.status_code == 200


def test_put_duplicate(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    body = {"balances": [{"currency_id": 1, "amount": "1.00"}, {"currency_id": 1, "amount": "2.00"}]}
    assert client.put("/cash-balances", json=body, headers=headers).json()["code"] == "duplicate_currency"


def test_put_atomic_nothing_applied_on_failure(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    # segunda entrada inválida (no holdable) → no se aplica ninguna
    body = {"balances": [{"currency_id": 1, "amount": "999.00"}, {"currency_id": 4, "amount": "10.00"}]}
    assert client.put("/cash-balances", json=body, headers=headers).status_code == 422
    rows = client.get("/cash-balances", headers=headers).json()
    assert next(x for x in rows if x["currency_id"] == 1)["amount"] == "0.00"  # Peso quedó en 0
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_balances.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_balance_service.py app/routers/cash_balances.py tests/test_cash_balances.py && git commit -m "feat: PUT /cash-balances (upsert masivo atómico)"
```

---

## Task 4: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (los previos + los nuevos de cash_balances).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/cash-balances` a `main` (1 commit). Push **manual**. (No tocar Notion.)

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** tabla PK compuesta + migración (Task 1); scoping holdable + 2 codes + schemas +
  get_balances + GET (Task 2); set_balances upsert atómico + PUT (Task 3). ✓
- **Placeholder scan:** sin TBD/TODO ni código roto. La migración se autogenera con checklist (no se fija el
  `down_revision` de antemano). ✓
- **Consistencia:** `CashBalanceOut`/`SetItem`/`Set`; `get_balances`/`set_balances`; `db.get(CashBalance,
  (user.id, currency_id))` (tupla en orden de PK); `require_holdable_currency` levanta `currency_not_available`.
  GET y PUT devuelven `list[CashBalanceOut]` (array pelado). ✓
- **Atomicidad:** se valida TODO el body (dups, holdable, ≥0) antes de cualquier escritura; el test
  `test_put_atomic_nothing_applied_on_failure` lo verifica. ✓
- **Sin Notion** en el cierre. ✓
