# user_financial_settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tabla `user_financial_settings` (monto mensual necesario, 1:1 con users) + el endpoint `cash_balances` actualiza/lee ese monto junto con los balances (respuesta pasa a objeto) + el timeline usa ese monto como `remaining_spending` del mes actual.

**Architecture:** Tabla nueva PK `user_id`. El PUT/GET `cash-balances` devuelven `{balances, monthly_need_amount}`; el PUT valida todo (balances + monto) antes de escribir, atómico, con `monthly_need_amount` opcional (`model_fields_set`). `get_timeline` lee el monto: el mes actual usa ese valor si está cargado, si no el prorrateo del dial.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · pytest.

**Spec:** [docs/superpowers/specs/2026-06-10-user-financial-settings-design.md](../specs/2026-06-10-user-financial-settings-design.md)

**Branch:** ya estás en `feat/user-financial-settings` (el spec ya está commiteado ahí). Squash-merge al final. **No tocar Notion.**

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`. Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

**Patrones del repo (verificados):** PK de una sola columna → `db.get(Modelo, user.id)` (sin tupla). `model_fields_set` para distinguir ausente vs null (patrón del PATCH de financings). `amount_negative` ya existe en `errors.py`. Tests sobre `margin_test` (`create_all` + savepoint). Una tabla **nueva** la crea `create_all` para los tests.

---

## File Structure

| Archivo | Cambio |
|---|---|
| `app/models/user_financial_settings.py` | modelo `UserFinancialSettings` (PK user_id) |
| `app/models/__init__.py` | registrar `UserFinancialSettings` |
| `alembic/versions/<rev>_create_user_financial_settings.py` | crea la tabla |
| `app/schemas/cash_balance.py` | `CashBalancesSet` + `monthly_need_amount`; nueva `CashBalancesView` |
| `app/services/cash_balance_service.py` | get/set con el monto + devolver `CashBalancesView` |
| `app/routers/cash_balances.py` | `response_model=CashBalancesView` |
| `app/services/cash_flow_entry_service.py` | `get_timeline`: mes actual lee `monthly_need` |
| `tests/test_cash_balances.py` | objeto en GET/PUT + tests del monto |
| `tests/test_get_cash_flow_entries.py` | timeline usa el monto |

---

## Task 1: Modelo + migración

**Files:** `app/models/user_financial_settings.py`, `app/models/__init__.py`, `alembic/versions/<rev>_create_user_financial_settings.py`, `tests/test_cash_balances.py`

- [ ] **Step 1: Test del modelo (rojo)** — agregar a `tests/test_cash_balances.py`:

```python
def test_insert_user_financial_settings(client, db_session, seed_uy_currency):
    from app.models.user_financial_settings import UserFinancialSettings
    user = _user(db_session, client)
    db_session.add(UserFinancialSettings(user_id=user.id, monthly_need_amount=Decimal("5000.00")))
    db_session.commit()
    row = db_session.get(UserFinancialSettings, user.id)
    assert row.monthly_need_amount == Decimal("5000.00")
```

- [ ] **Step 2: Run → rojo**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_balances.py::test_insert_user_financial_settings -q`
Expected: FALLA (`ModuleNotFoundError: app.models.user_financial_settings`).

- [ ] **Step 3: Modelo** `app/models/user_financial_settings.py`:

```python
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserFinancialSettings(Base):
    __tablename__ = "user_financial_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    monthly_need_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Registrar el modelo** en `app/models/__init__.py` (al final):

```python
from app.models.user_financial_settings import UserFinancialSettings  # noqa: F401
```

- [ ] **Step 5: Run → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_balances.py::test_insert_user_financial_settings -q`
Expected: PASS.

- [ ] **Step 6: Migración (autogenerate + verificación)**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic upgrade head && alembic revision --autogenerate -m "create user_financial_settings"
```

Abrir el archivo generado y verificar: `upgrade()` crea `user_financial_settings` con PK `user_id`, FK a `users.id`, `monthly_need_amount` numeric(12,2) nullable, timestamps; `downgrade()` hace `op.drop_table('user_financial_settings')`. Sin cambios espurios. Aplicar:

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic upgrade head
```

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/user_financial_settings.py app/models/__init__.py alembic/versions/ tests/test_cash_balances.py && git commit -m "feat: tabla user_financial_settings (modelo + migración)"
```

---

## Task 2: cash_balances devuelve objeto + lee/escribe el monto

**Files:** `app/schemas/cash_balance.py`, `app/services/cash_balance_service.py`, `app/routers/cash_balances.py`, `tests/test_cash_balances.py`

- [ ] **Step 1: Tests nuevos (rojo)** — agregar a `tests/test_cash_balances.py`:

```python
def test_get_includes_monthly_need_null_default(client, db_session, seed_uy_currency):
    headers = _headers(client)
    body = client.get("/cash-balances", headers=headers).json()
    assert body["monthly_need_amount"] is None
    assert isinstance(body["balances"], list)


def test_put_sets_monthly_need(client, db_session, seed_uy_currency):
    headers = _headers(client)
    r = client.put("/cash-balances", json={"balances": [], "monthly_need_amount": "5000.00"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["monthly_need_amount"] == "5000.00"
    assert client.get("/cash-balances", headers=headers).json()["monthly_need_amount"] == "5000.00"


def test_put_absent_monthly_need_untouched(client, db_session, seed_uy_currency):
    headers = _headers(client)
    client.put("/cash-balances", json={"balances": [], "monthly_need_amount": "5000.00"}, headers=headers)
    client.put("/cash-balances", json={"balances": [{"currency_id": 1, "amount": "100.00"}]}, headers=headers)
    assert client.get("/cash-balances", headers=headers).json()["monthly_need_amount"] == "5000.00"


def test_put_null_clears_monthly_need(client, db_session, seed_uy_currency):
    headers = _headers(client)
    client.put("/cash-balances", json={"balances": [], "monthly_need_amount": "5000.00"}, headers=headers)
    client.put("/cash-balances", json={"balances": [], "monthly_need_amount": None}, headers=headers)
    assert client.get("/cash-balances", headers=headers).json()["monthly_need_amount"] is None


def test_put_monthly_need_negative(client, db_session, seed_uy_currency):
    headers = _headers(client)
    r = client.put("/cash-balances", json={"balances": [], "monthly_need_amount": "-1.00"}, headers=headers)
    assert r.json()["code"] == "amount_negative"


def test_put_atomic_monthly_need_invalid(client, db_session, seed_uy_currency):
    headers = _headers(client)
    body = {"balances": [{"currency_id": 1, "amount": "999.00"}], "monthly_need_amount": "-5.00"}
    assert client.put("/cash-balances", json=body, headers=headers).status_code == 422
    after = client.get("/cash-balances", headers=headers).json()
    assert next(x for x in after["balances"] if x["currency_id"] == 1)["amount"] == "0.00"  # balances no aplicados
    assert after["monthly_need_amount"] is None
```

- [ ] **Step 2: Run → rojo**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_balances.py::test_put_sets_monthly_need -q`
Expected: FALLA (el body no acepta `monthly_need_amount` / la respuesta es array sin esa clave).

- [ ] **Step 3: Schemas** — reescribir `app/schemas/cash_balance.py`:

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
    monthly_need_amount: Decimal | None = None


class CashBalancesView(BaseModel):
    balances: list[CashBalanceOut]
    monthly_need_amount: Decimal | None
```

- [ ] **Step 4: Service** — reescribir `app/services/cash_balance_service.py`:

```python
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.cash_balance import CashBalance
from app.models.user import User
from app.models.user_financial_settings import UserFinancialSettings
from app.schemas.cash_balance import CashBalanceOut, CashBalancesSet, CashBalancesView
from app.services.scoping import holdable_currencies, require_holdable_currency


def _monthly_need(db: Session, user: User) -> Decimal | None:
    s = db.get(UserFinancialSettings, user.id)
    return s.monthly_need_amount if s is not None else None


def get_balances(db: Session, user: User) -> CashBalancesView:
    stored = {
        b.currency_id: b.amount
        for b in db.execute(select(CashBalance).where(CashBalance.user_id == user.id)).scalars()
    }
    balances = [
        CashBalanceOut(currency_id=c.id, amount=stored.get(c.id, Decimal("0.00")))
        for c in holdable_currencies(db, user)
    ]
    return CashBalancesView(balances=balances, monthly_need_amount=_monthly_need(db, user))


def set_balances(db: Session, user: User, payload: CashBalancesSet) -> CashBalancesView:
    # validar TODO el body antes de escribir (atómico)
    seen: set[int] = set()
    for item in payload.balances:
        if item.currency_id in seen:
            raise AppError(ErrorCode.duplicate_currency, field="currency_id")
        seen.add(item.currency_id)
        require_holdable_currency(db, user, item.currency_id)  # 422 currency_not_available
        if item.amount < 0:
            raise AppError(ErrorCode.amount_negative, field="amount")

    set_need = "monthly_need_amount" in payload.model_fields_set
    if set_need and payload.monthly_need_amount is not None and payload.monthly_need_amount < 0:
        raise AppError(ErrorCode.amount_negative, field="monthly_need_amount")

    for item in payload.balances:
        row = db.get(CashBalance, (user.id, item.currency_id))
        if row is None:
            db.add(CashBalance(user_id=user.id, currency_id=item.currency_id, amount=item.amount))
        else:
            row.amount = item.amount

    if set_need:
        s = db.get(UserFinancialSettings, user.id)
        if s is None:
            db.add(UserFinancialSettings(user_id=user.id, monthly_need_amount=payload.monthly_need_amount))
        else:
            s.monthly_need_amount = payload.monthly_need_amount

    db.flush()
    db.commit()
    return get_balances(db, user)
```

- [ ] **Step 5: Router** — en `app/routers/cash_balances.py`, cambiar el import y los `response_model`:

```python
from app.schemas.cash_balance import CashBalancesSet, CashBalancesView
```
```python
@router.get("/cash-balances", response_model=CashBalancesView)
def list_balances(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CashBalancesView:
    return svc.get_balances(db, user)


@router.put("/cash-balances", response_model=CashBalancesView)
def set_balances(
    payload: CashBalancesSet,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CashBalancesView:
    return svc.set_balances(db, user, payload)
```

- [ ] **Step 6: Actualizar los tests viejos al objeto** — en `tests/test_cash_balances.py`:

`test_get_lists_holdable_zero_default`:
```python
    body = client.get("/cash-balances", headers=headers).json()
    assert body["balances"] == [{"currency_id": 1, "amount": "0.00"}, {"currency_id": 3, "amount": "0.00"}]
    assert body["monthly_need_amount"] is None
```

`test_put_sets_multiple_atomic`:
```python
    r = client.put("/cash-balances", json=body, headers=headers)
    assert r.status_code == 200
    assert r.json()["balances"] == [{"currency_id": 1, "amount": "15000.00"}, {"currency_id": 3, "amount": "200.00"}]
```

`test_put_upsert_updates` (última línea):
```python
    body = client.get("/cash-balances", headers=headers).json()["balances"]
    assert next(x for x in body if x["currency_id"] == 1)["amount"] == "500.00"
```

`test_put_atomic_nothing_applied_on_failure` (últimas dos líneas):
```python
    body = client.get("/cash-balances", headers=headers).json()["balances"]
    assert next(x for x in body if x["currency_id"] == 1)["amount"] == "0.00"  # Peso quedó en 0
```

- [ ] **Step 7: Run el archivo → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_balances.py -q`
Expected: PASS (viejos actualizados + nuevos del monto).

- [ ] **Step 8: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/schemas/cash_balance.py app/services/cash_balance_service.py app/routers/cash_balances.py tests/test_cash_balances.py && git commit -m "feat: cash_balances devuelve objeto y gestiona monthly_need_amount"
```

---

## Task 3: Timeline usa el monto en el mes actual

**Files:** `app/services/cash_flow_entry_service.py`, `tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Tests nuevos (rojo)** — agregar a `tests/test_get_cash_flow_entries.py`:

```python
def _set_need(db_session, user, amount):
    from app.models.user_financial_settings import UserFinancialSettings
    db_session.add(UserFinancialSettings(user_id=user.id, monthly_need_amount=Decimal(amount)))
    db_session.commit()


def test_remaining_spending_uses_monthly_need_when_set(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan_dial(db_session, user, "42000.00")
    _set_need(db_session, user, "5000.00")
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="1000.00")
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    assert out.months[0].remaining_spending == Decimal("5000.00")  # el monto del usuario, no el prorrateo


def test_remaining_spending_falls_back_to_prorated_dial(client, db_session, seed_cc_refs):
    headers = _headers(client)
    user = _last_user(db_session)
    plan = _plan_dial(db_session, user, "42000.00")  # sin user_financial_settings
    _card_entry(db_session, user, event_date=date(2026, 6, 10), amount="1000.00")
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    assert out.months[0].remaining_spending == Decimal("29400.00")  # (30-9)/30 * 42000
```

- [ ] **Step 2: Run → rojo**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_remaining_spending_uses_monthly_need_when_set -q`
Expected: FALLA (`remaining_spending == 29400.00`, todavía usa el prorrateo).

- [ ] **Step 3: Leer el monto en `get_timeline`** — en `app/services/cash_flow_entry_service.py`:

Agregar el import al tope:
```python
from app.models.user_financial_settings import UserFinancialSettings
```

Tras calcular `dial_prorated` (antes de `rows = db.execute(...)`), agregar:
```python
    _settings = db.get(UserFinancialSettings, user.id)
    monthly_need = _settings.monthly_need_amount if _settings is not None else None
```

- [ ] **Step 4: Usar el monto en el ancla del mes actual** — reemplazar, dentro del branch `if prev_balance is None:`, la línea
`remaining_spending = dial_prorated if key == current_key else dial` por:

```python
                if key == current_key:
                    remaining_spending = monthly_need if monthly_need is not None else dial_prorated
                else:
                    remaining_spending = dial
```

- [ ] **Step 5: Run los tests nuevos → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py::test_remaining_spending_uses_monthly_need_when_set tests/test_get_cash_flow_entries.py::test_remaining_spending_falls_back_to_prorated_dial -q`
Expected: PASS.

- [ ] **Step 6: Run el archivo → verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_get_cash_flow_entries.py -q`
Expected: PASS (los demás tests no siembran `user_financial_settings` → siguen con el prorrateo del dial).

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_entry_service.py tests/test_get_cash_flow_entries.py && git commit -m "feat: timeline usa monthly_need_amount como remaining_spending del mes actual"
```

---

## Task 4: Suite completa + cierre

- [ ] **Step 1: Suite completa**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q`
Expected: todo verde.

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado: **squash-merge** de `feat/user-financial-settings` a `main` (1 commit). Push **manual**. (No tocar Notion.)

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** §1 tabla + migración (Task 1); §2/§3/§4 endpoint objeto + monto + atómico (Task 2); §5 integración timeline (Task 3). ✓
- **Placeholder scan:** sin TBD/TODO; todo el código está escrito; `<rev>` es la convención de Alembic. ✓
- **Consistencia de tipos/nombres:** `UserFinancialSettings`/`monthly_need_amount`; `CashBalancesView`/`CashBalancesSet`; `get_balances`/`set_balances` devuelven `CashBalancesView`; `db.get(UserFinancialSettings, user.id)` (PK de una columna); `monthly_need`/`_monthly_need`. ✓
- **Atomicidad:** la validación de `monthly_need_amount` (`amount_negative`) corre en la fase de validación, antes de cualquier escritura; `test_put_atomic_monthly_need_invalid` lo verifica. ✓
- **Tests viejos:** los de `cash_balances` se actualizan al objeto en Task 2 Step 6; los del timeline que no siembran `user_financial_settings` siguen verdes (fallback al prorrateo). ✓
- **Sin Notion** en el cierre. ✓
```