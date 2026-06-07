# Crear el plan default al registrarse — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que `POST /auth/register` cree el plan default del usuario en la misma transacción que `users` + `auth_identities`.

**Architecture:** Nuevo `app/services/plan_service.py` con `create_default_plan(db, user)` (no hace commit). `auth_service.register_user` lo llama después de crear user+identity y antes de su `commit`. Un fixture nuevo `seed_uy_currency` siembra la moneda de curso legal para los tests de auth.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pytest. Python 3.13 (`backend/.venv`).

**Spec:** `docs/superpowers/specs/2026-06-07-register-default-plan-design.md`.

**Git:** rama `feat/register-default-plan`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/
├── services/plan_service.py   # create_default_plan(db, user)   (NUEVO)
└── services/auth_service.py    # register_user llama a create_default_plan   (MODIFICAR)
backend/tests/
├── conftest.py                 # + fixture seed_uy_currency   (MODIFICAR)
├── test_auth_register.py       # usar seed_uy_currency + test del plan default   (MODIFICAR)
└── test_auth_login.py          # usar seed_uy_currency   (MODIFICAR)
```

> **Nota de ejecución:** apenas se cablee `create_default_plan` en `register_user` (Step 5), los tests de
> auth que hoy usan `seed_uy` (sin currency) van a fallar — por eso el Step 6 los cambia a
> `seed_uy_currency`. El estado final de la tarea es verde; el rojo transitorio entre Step 5 y 6 es esperado.

---

## Task 1: plan default en el registro (TDD)

**Files:**
- Create: `backend/app/services/plan_service.py`
- Modify: `backend/app/services/auth_service.py`, `backend/tests/conftest.py`, `backend/tests/test_auth_register.py`, `backend/tests/test_auth_login.py`

- [ ] **Step 1: Agregar el fixture `seed_uy_currency` a `backend/tests/conftest.py`**

Al final del archivo:

```python
@pytest.fixture
def seed_uy_currency(db_session, seed_uy):
    from app.models.currency import Currency

    db_session.add(
        Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True)
    )
    db_session.flush()
```

- [ ] **Step 2: Escribir el test que falla en `backend/tests/test_auth_register.py`**

Agregar al final del archivo:

```python
def test_register_creates_default_plan(client, db_session, seed_uy_currency):
    from decimal import Decimal

    from app.models.plan import Plan

    client.post("/auth/register", json={"email": "p@b.com", "password": "12345678"})

    plans = db_session.execute(select(Plan)).scalars().all()
    assert len(plans) == 1
    plan = plans[0]
    assert plan.is_default is True
    assert plan.is_engine_generated is False
    assert plan.name == "Mi plan actual"
    assert plan.dial_amount == Decimal("0")
    assert plan.dial_currency_id == 1
    assert plan.goal_kind is None
    assert plan.goal_amount is None
    assert plan.goal_currency_id is None
    assert plan.selected_at is not None
```

(El `from sqlalchemy import select` ya está importado al tope de ese archivo.)

- [ ] **Step 3: Correr y verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_auth_register.py::test_register_creates_default_plan -v`
Expected: FALLA — `assert len(plans) == 1` falla con 0 (el registro todavía no crea plan).

- [ ] **Step 4: Crear `backend/app/services/plan_service.py`**

```python
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.currency import Currency
from app.models.plan import Plan
from app.models.user import User

DEFAULT_PLAN_NAME = "Mi plan actual"


def create_default_plan(db: Session, user: User) -> Plan:
    """Crea el plan default del usuario (representa su realidad actual). No hace commit:
    la transacción la controla el caller (register_user)."""
    currency = db.execute(
        select(Currency).where(
            Currency.country_code == user.country_code,
            Currency.is_legal_tender.is_(True),
        )
    ).scalars().first()

    plan = Plan(
        user_id=user.id,
        name=DEFAULT_PLAN_NAME,
        is_default=True,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("0"),
        dial_currency_id=currency.id,
        goal_kind=None,
        goal_amount=None,
        goal_currency_id=None,
    )
    db.add(plan)
    return plan
```

- [ ] **Step 5: Cablear en `backend/app/services/auth_service.py`**

Agregar el import (con los demás `from app.services...`/imports de servicio; si no hay, ponerlo junto a los imports de `app.`):

```python
from app.services import plan_service
```

En `register_user`, entre `db.add(identity)` y el `try:` del commit, agregar la llamada:

```python
    db.add(identity)
    plan_service.create_default_plan(db, user)
    try:
        db.commit()
```

(`user.id` ya está disponible porque `register_user` hace `db.flush()` tras `db.add(user)`.)

- [ ] **Step 6: Cambiar los tests de auth a `seed_uy_currency`**

En `backend/tests/test_auth_register.py` y `backend/tests/test_auth_login.py`, reemplazar el parámetro de fixture `seed_uy` por `seed_uy_currency` en **todas** las funciones de test que lo usan (el registro ahora necesita la moneda para crear el plan). Ejemplos:
- `def test_register_creates_user_and_returns_token(client, db_session, seed_uy):` → `(client, db_session, seed_uy_currency):`
- `def test_register_token_contains_user_id(client, seed_uy):` → `(client, seed_uy_currency):`
- `def test_login_ok(client, seed_uy):` → `(client, seed_uy_currency):`
- …y así con cada test de esos dos archivos que reciba `seed_uy`.

- [ ] **Step 7: Correr los tests de auth y verificar que pasan**

Run: `pytest tests/test_auth_register.py tests/test_auth_login.py -v`
Expected: PASAN todos (incluido `test_register_creates_default_plan`).

- [ ] **Step 8: Regresión de la suite completa**

Run: `pytest -q`
Expected: pasan todos.

- [ ] **Step 9: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/plan_service.py backend/app/services/auth_service.py backend/tests/conftest.py backend/tests/test_auth_register.py backend/tests/test_auth_login.py
git commit -m "feat(backend): crear el plan default al registrarse"
```

---

## Notas de cierre

- Al terminar: registrarse crea `users` + `auth_identities` + el `plans` default, todo en una transacción. El contrato de `POST /auth/register` no cambia.
- **Cierre:** squash-merge de `feat/register-default-plan` → un commit `feat: plan default al registrarse` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** plan default en la misma transacción (§1) — Step 5 (llamada antes del commit) ✓; `plan_service.create_default_plan` sin commit (§2) — Step 4 ✓; valores del plan default (§3) — Step 4 ✓; moneda de curso legal derivada del país (§4) — Step 4 query ✓; fixture `seed_uy_currency` + switch de tests + test nuevo (§5) — Steps 1/2/6 ✓; contrato de register sin cambios (no se toca el router ni el response) ✓.
- **Placeholders:** ninguno; código completo en cada paso.
- **Consistencia de tipos:** `create_default_plan(db, user) -> Plan` con la firma usada en `register_user`; el `Plan(...)` usa exactamente las columnas del modelo (`is_default`, `is_engine_generated`, `selected_at`, `dial_amount`, `dial_currency_id`, `goal_*`); el test referencia esas mismas columnas; `seed_uy_currency` siembra `Currency(id=1)` y el test asume `dial_currency_id == 1`.
```
