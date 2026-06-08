# Scoping por país (módulo compartido) — Plan de implementación

> **For agentic workers:** Ejecutar **inline** en la sesión principal (decisión del proyecto: las tasks
> con muchos comandos van inline, no por subagentes — ver memoria `subagent-permission-prompts`). Mantener
> el rigor TDD: test → rojo → implementación → verde → commit por task. Steps con checkbox (`- [ ]`).

**Goal:** Centralizar la regla "una entidad referenciada pertenece al país del usuario" en un módulo
compartido `app/services/scoping.py`, eliminando la duplicación de `_validate_currency` y dejando el riel
listo para Obligaciones.

**Architecture:** Primitiva genérica `require_country_scoped` (la regla, en un lugar) + wrapper tipado
`require_user_currency` (le da nombre y error code) + `legal_tender_currency` movida desde `plan_service`.
Los 3 servicios (incomes, plan_movements, plans) importan del módulo. Refactor que preserva comportamiento:
la suite existente es la red de seguridad.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, pytest. Spec:
`docs/superpowers/specs/2026-06-08-scoping-por-pais-design.md`.

**Rama:** `feat/scoping-por-pais` → squash-merge a `main`.

---

## Task 0: Crear la rama

- [ ] **Step 1: Crear y cambiar a la rama de feature**

```bash
git checkout -b feat/scoping-por-pais
```

---

## Task 1: Módulo `scoping.py` (genérica + wrapper + derivar)

**Files:**
- Create: `backend/app/services/scoping.py`
- Test: `backend/tests/test_scoping.py`

- [ ] **Step 1: Escribir los tests (rojo)**

`backend/tests/test_scoping.py`:

```python
import pytest

from app.core.errors import AppError, ErrorCode
from app.models.currency import Currency
from app.models.user import User
from app.services.scoping import (
    legal_tender_currency,
    require_country_scoped,
    require_user_currency,
)


def _user(db_session, country_code="UY"):
    user = User(
        email="scoping@test.com",
        password_hash="x",
        auth_provider="email",
        country_code=country_code,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _other_country_currency(db_session):
    """Currency de un país distinto a UY para los casos negativos."""
    db_session.add(Country(code="AR", name="Argentina", vat_rate=Decimal("21.00")))
    db_session.flush()
    currency = Currency(
        country_code="AR",
        code="ARS",
        name="Peso argentino",
        symbol="$",
        is_legal_tender=True,
    )
    db_session.add(currency)
    db_session.flush()
    return currency


def test_require_country_scoped_returns_entity_of_user_country(
    db_session, seed_uy, seed_uy_currency
):
    user = _user(db_session)
    result = require_country_scoped(
        db_session, user, Currency, seed_uy_currency.id,
        error=ErrorCode.currency_not_available, field="currency_id",
    )
    assert result.id == seed_uy_currency.id


def test_require_country_scoped_raises_for_other_country(
    db_session, seed_uy, seed_uy_currency
):
    user = _user(db_session)
    other = _other_country_currency(db_session)
    with pytest.raises(AppError) as exc:
        require_country_scoped(
            db_session, user, Currency, other.id,
            error=ErrorCode.currency_not_available, field="currency_id",
        )
    assert exc.value.code == ErrorCode.currency_not_available
    assert exc.value.field == "currency_id"


def test_require_country_scoped_raises_for_none_id(db_session, seed_uy):
    user = _user(db_session)
    with pytest.raises(AppError):
        require_country_scoped(
            db_session, user, Currency, None,
            error=ErrorCode.currency_not_available, field="currency_id",
        )


def test_require_country_scoped_raises_for_missing_id(db_session, seed_uy):
    user = _user(db_session)
    with pytest.raises(AppError):
        require_country_scoped(
            db_session, user, Currency, 999999,
            error=ErrorCode.currency_not_available, field="currency_id",
        )


def test_require_user_currency_returns_currency_of_country(
    db_session, seed_uy, seed_uy_currency
):
    user = _user(db_session)
    result = require_user_currency(db_session, user, seed_uy_currency.id)
    assert result.id == seed_uy_currency.id


def test_require_user_currency_raises_for_other_country(
    db_session, seed_uy, seed_uy_currency
):
    user = _user(db_session)
    other = _other_country_currency(db_session)
    with pytest.raises(AppError) as exc:
        require_user_currency(db_session, user, other.id)
    assert exc.value.code == ErrorCode.currency_not_available
    assert exc.value.field == "currency_id"


def test_legal_tender_currency_returns_country_legal_tender(
    db_session, seed_uy, seed_uy_currency
):
    user = _user(db_session)
    result = legal_tender_currency(db_session, user)
    assert result.id == seed_uy_currency.id
    assert result.is_legal_tender is True
```

> Nota: agregar `from decimal import Decimal` y `from app.models.country import Country` arriba (los usa
> `_other_country_currency`). Confirmar nombres de columnas reales de `Currency`/`User`/`Country` al
> escribir (ajustar el constructor si difiere; ej. campos NOT NULL adicionales).

- [ ] **Step 2: Correr los tests, verificar que fallan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_scoping.py -q
```
Esperado: FAIL (ModuleNotFoundError: app.services.scoping).

- [ ] **Step 3: Implementar el módulo**

`backend/app/services/scoping.py`:

```python
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.currency import Currency
from app.models.user import User

T = TypeVar("T")


def require_country_scoped(
    db: Session,
    user: User,
    model: type[T],
    entity_id,
    *,
    error: ErrorCode,
    field: str,
) -> T:
    """Devuelve la entidad `model` con `entity_id` si pertenece al país del usuario.

    Lanza AppError(error, field=field) si no existe o es de otro país.
    Convención: `model` debe exponer la columna `country_code`.
    """
    entity = db.get(model, entity_id) if entity_id is not None else None
    if entity is None or entity.country_code != user.country_code:
        raise AppError(error, field=field)
    return entity


def require_user_currency(db: Session, user: User, currency_id: int | None) -> Currency:
    """Valida que la moneda enviada por el usuario sea de su país."""
    return require_country_scoped(
        db, user, Currency, currency_id,
        error=ErrorCode.currency_not_available, field="currency_id",
    )


def legal_tender_currency(db: Session, user: User) -> Currency:
    """Moneda de curso legal del país del usuario (se deriva, no viene del body)."""
    return db.execute(
        select(Currency).where(
            Currency.country_code == user.country_code,
            Currency.is_legal_tender.is_(True),
        )
    ).scalars().first()
```

- [ ] **Step 4: Correr los tests, verificar que pasan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_scoping.py -q
```
Esperado: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoping.py backend/tests/test_scoping.py
git commit -m "feat: módulo scoping (require_country_scoped + currency)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Migrar `income_service` a `require_user_currency`

**Files:**
- Modify: `backend/app/services/income_service.py`

- [ ] **Step 1: Importar y reemplazar**

Agregar el import:
```python
from app.services.scoping import require_user_currency
```
Borrar la función `_validate_currency` (líneas 27-30) y reemplazar sus 2 llamadas
(`_validate_currency(db, user, payload.currency_id)`) por:
```python
require_user_currency(db, user, payload.currency_id)
```
Quitar `from app.models.currency import Currency` si quedó sin uso (verificar con grep antes).

- [ ] **Step 2: Verificar que no quedó referencia colgada**

```bash
cd /Users/tachone/proyectos/margin/backend && grep -n "_validate_currency\|Currency" app/services/income_service.py
```
Esperado: sin `_validate_currency`; `Currency` solo si todavía se usa en otro lado.

- [ ] **Step 3: Correr los tests de incomes**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_incomes.py -q
```
Esperado: PASS (sin cambios respecto a antes).

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/income_service.py
git commit -m "refactor: income_service usa scoping.require_user_currency

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Migrar `plan_movement_service` a `require_user_currency`

**Files:**
- Modify: `backend/app/services/plan_movement_service.py`

- [ ] **Step 1: Importar y reemplazar**

Agregar `from app.services.scoping import require_user_currency`. Borrar `_validate_currency`
(líneas 41-44) y reemplazar sus 2 llamadas por `require_user_currency(db, user, payload.currency_id)`.
Quitar el import de `Currency` si quedó sin uso.

- [ ] **Step 2: Verificar**

```bash
cd /Users/tachone/proyectos/margin/backend && grep -n "_validate_currency\|Currency" app/services/plan_movement_service.py
```

- [ ] **Step 3: Correr los tests de plan_movements**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_plan_movements.py -q
```
Esperado: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/plan_movement_service.py
git commit -m "refactor: plan_movement_service usa scoping.require_user_currency

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Migrar `plan_service` a `legal_tender_currency`

**Files:**
- Modify: `backend/app/services/plan_service.py`

- [ ] **Step 1: Importar y reemplazar**

Agregar `from app.services.scoping import legal_tender_currency`. Borrar `_legal_tender_currency`
(líneas 21-27) y reemplazar los 3 usos (`_legal_tender_currency(db, user)`) por
`legal_tender_currency(db, user)`. Quitar `from app.models.currency import Currency` y `select` de
sqlalchemy si quedaron sin uso (verificar con grep — `select`/`update` pueden seguir usándose).

- [ ] **Step 2: Verificar**

```bash
cd /Users/tachone/proyectos/margin/backend && grep -n "_legal_tender_currency\|Currency\|select" app/services/plan_service.py
```

- [ ] **Step 3: Correr los tests de plans**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_plans.py -q
```
Esperado: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/plan_service.py
git commit -m "refactor: plan_service usa scoping.legal_tender_currency

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Documentar la convención + suite completa

**Files:**
- Modify: `backend/CLAUDE.md`

- [ ] **Step 1: Agregar la convención en `backend/CLAUDE.md`**

En la sección "Convenciones", agregar una línea:
```markdown
- Scoping por país: una referencia que debe ser del país del usuario (ej. `currency_id`) se valida con
  `app/services/scoping.py` (`require_user_currency`, o `require_country_scoped` para un modelo nuevo con
  columna `country_code`). No duplicar la regla en cada servicio.
```

- [ ] **Step 2: Correr la suite completa (red de seguridad)**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```
Esperado: PASS (todo verde, incluido test_scoping; mismo total que antes + 7 nuevos).

- [ ] **Step 3: Commit**

```bash
git add backend/CLAUDE.md
git commit -m "docs: convención de scoping por país en backend/CLAUDE.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Cierre

Tras Task 5 verde: usar **finishing-a-development-branch** → squash-merge `feat/scoping-por-pais` a `main`
(1 commit por feature) → push (manual/prompteado).
