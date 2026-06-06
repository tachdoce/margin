# Bootstrap (`GET /bootstrap`) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar `get_current_user` (auth para rutas protegidas) y `GET /bootstrap`, que devuelve los 8 catálogos curados y filtrados por país en un wrapper `{version, catalogs}`.

**Architecture:** Dependency `get_current_user` (valida JWT, carga User, 401 si falla) reusable. Router finito → servicio que arma los catálogos desde la DB → schemas Pydantic curados por catálogo. Read-only.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, python-jose, pytest. Python 3.13 (`backend/.venv`).

**Spec:** `docs/superpowers/specs/2026-06-06-bootstrap-design.md`.

**Git:** rama `feat/bootstrap`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/
├── core/
│   ├── config.py            # + bootstrap_version   (MODIFICAR)
│   └── deps.py              # get_current_user + resolve_user_from_token   (NUEVO)
├── schemas/bootstrap.py      # schemas por catálogo + BootstrapResponse   (NUEVO)
├── services/bootstrap_service.py  # build_catalogs(db, user)   (NUEVO)
├── routers/bootstrap.py      # GET /bootstrap   (NUEVO)
└── main.py                  # montar bootstrap router   (MODIFICAR)
backend/tests/
├── test_deps.py             # get_current_user (unit)   (NUEVO)
└── test_bootstrap.py         # endpoint   (NUEVO)
```

---

## Task 1: `get_current_user` (auth dependency) — TDD

**Files:** Create `backend/app/core/deps.py`, `backend/tests/test_deps.py`

- [ ] **Step 1: Tests que fallan `backend/tests/test_deps.py`**

```python
from datetime import datetime, timezone

import pytest

from app.core.deps import resolve_user_from_token
from app.core.errors import AppError, ErrorCode
from app.core.security import create_access_token
from app.models.user import User


def _make_user(db_session):
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    return user


def test_resolve_user_valid_token(db_session, seed_uy):
    user = _make_user(db_session)
    result = resolve_user_from_token(create_access_token(user.id), db_session)
    assert result.id == user.id


def test_resolve_user_no_token(db_session):
    with pytest.raises(AppError) as exc:
        resolve_user_from_token(None, db_session)
    assert exc.value.code == ErrorCode.unauthenticated


def test_resolve_user_invalid_token(db_session):
    with pytest.raises(AppError) as exc:
        resolve_user_from_token("not-a-jwt", db_session)
    assert exc.value.code == ErrorCode.unauthenticated


def test_resolve_user_soft_deleted(db_session, seed_uy):
    user = _make_user(db_session)
    user.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    with pytest.raises(AppError) as exc:
        resolve_user_from_token(create_access_token(user.id), db_session)
    assert exc.value.code == ErrorCode.unauthenticated
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_deps.py -v`
Expected: FALLA (`ModuleNotFoundError: No module named 'app.core.deps'`).

- [ ] **Step 3: Implementar `backend/app/core/deps.py`**

```python
import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def resolve_user_from_token(token: str | None, db: Session) -> User:
    """Núcleo testeable: del token al User, o AppError(unauthenticated)."""
    if not token:
        raise AppError(ErrorCode.unauthenticated)
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise AppError(ErrorCode.unauthenticated)
    raw_id = payload.get("user_id")
    try:
        user_id = uuid.UUID(str(raw_id))
    except (ValueError, TypeError):
        raise AppError(ErrorCode.unauthenticated)
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AppError(ErrorCode.unauthenticated)
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency de FastAPI para rutas protegidas."""
    token = credentials.credentials if credentials else None
    return resolve_user_from_token(token, db)
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_deps.py -v`
Expected: PASAN los 4 tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/core/deps.py backend/tests/test_deps.py
git commit -m "feat(backend): get_current_user (auth dependency para rutas protegidas)"
```

---

## Task 2: Config + schemas del bootstrap

**Files:** Modify `backend/app/core/config.py`, Create `backend/app/schemas/bootstrap.py`

- [ ] **Step 1: Agregar `bootstrap_version` a `Settings` (`backend/app/core/config.py`)**

Agregar dentro de `Settings`, después de `cors_origins`:

```python
    bootstrap_version: str = "1"
```

- [ ] **Step 2: Crear `backend/app/schemas/bootstrap.py`**

```python
from pydantic import BaseModel, ConfigDict


class _Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CurrencyOut(_Read):
    id: int
    name: str
    is_legal_tender: bool


class ObligationTypeOut(_Read):
    id: int
    obligation_kind: str
    code: str
    name: str
    description: str
    default_priority_level: int


class IncomeTypeOut(_Read):
    id: int
    code: str
    name: str


class PriorityLevelOut(_Read):
    level: int
    name: str
    description: str


class InstitutionOut(_Read):
    id: int
    name: str


class ReviewFindingCodeOut(_Read):
    code: str
    message: str


class CreditCardNetworkOut(_Read):
    id: int
    code: str
    name: str


class CreditCardItemTypeOut(_Read):
    id: int
    code: str
    name: str
    description: str


class Catalogs(BaseModel):
    currencies: list[CurrencyOut]
    obligation_types: list[ObligationTypeOut]
    income_types: list[IncomeTypeOut]
    priority_levels: list[PriorityLevelOut]
    institutions: list[InstitutionOut]
    review_finding_codes: list[ReviewFindingCodeOut]
    credit_card_networks: list[CreditCardNetworkOut]
    credit_card_item_types: list[CreditCardItemTypeOut]


class BootstrapResponse(BaseModel):
    version: str
    catalogs: Catalogs
```

- [ ] **Step 3: Verificar que importa y la config carga**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && python -c "from app.schemas.bootstrap import BootstrapResponse; from app.core.config import settings; print(settings.bootstrap_version)"`
Expected: `1`

- [ ] **Step 4: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/core/config.py backend/app/schemas/bootstrap.py
git commit -m "feat(backend): config bootstrap_version y schemas de catálogos"
```

---

## Task 3: Servicio + endpoint `GET /bootstrap` — TDD

**Files:** Create `backend/app/services/bootstrap_service.py`, `backend/app/routers/bootstrap.py`, `backend/tests/test_bootstrap.py`, Modify `backend/app/main.py`

- [ ] **Step 1: Tests que fallan `backend/tests/test_bootstrap.py`**

```python
from decimal import Decimal

from app.models.country import Country
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_network import CreditCardNetwork
from app.models.currency import Currency
from app.models.income_type import IncomeType
from app.models.institution import Institution
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.review_finding_code import ReviewFindingCode

CATALOG_KEYS = {
    "currencies", "obligation_types", "income_types", "priority_levels",
    "institutions", "review_finding_codes", "credit_card_networks", "credit_card_item_types",
}


def _seed_catalogs(db_session):
    # segundo país para probar el filtrado por país
    db_session.add(Country(code="AR", name="Argentina", visible=True, vat_rate=Decimal("21.00")))
    db_session.add_all([
        Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True),
        Currency(id=99, country_code="AR", name="Peso AR", is_legal_tender=True, allowed_in_credit_card=False),
        PriorityLevel(level=1, name="Ineludible", description="x"),
        PriorityLevel(level=2, name="Esencial", description="x"),
        IncomeType(id=1, code="sueldo", name="Sueldo", visible=True),
        IncomeType(id=2, code="oculto", name="Oculto", visible=False),
        ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler", description="x", default_priority_level=2, visible=True),
        Institution(id=1, country_code="UY", name="BROU", visible=True),
        Institution(id=2, country_code="AR", name="Banco AR", visible=True),
        ReviewFindingCode(code="amount_above_threshold", message="x"),
        CreditCardNetwork(id=1, country_code="UY", code="visa", name="Visa"),
        CreditCardItemType(id=1, code="compra", name="Compra", description="x"),
    ])
    db_session.flush()


def _register_token(client):
    return client.post("/auth/register", json={"email": "u@b.com", "password": "12345678"}).json()["token"]


def test_bootstrap_requires_auth(client, seed_uy):
    resp = client.get("/bootstrap")
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_bootstrap_returns_catalogs(client, db_session, seed_uy):
    token = _register_token(client)
    _seed_catalogs(db_session)

    resp = client.get("/bootstrap", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"]
    catalogs = body["catalogs"]
    assert set(catalogs.keys()) == CATALOG_KEYS
    # filtrado por país: solo data de UY
    assert {c["name"] for c in catalogs["currencies"]} == {"Peso"}
    assert {i["name"] for i in catalogs["institutions"]} == {"BROU"}
    # priority_levels: todos (incluye el nivel 1)
    levels = {p["level"] for p in catalogs["priority_levels"]}
    assert 1 in levels and 2 in levels
    # income_types: el visible=false no aparece
    assert all(it["code"] != "oculto" for it in catalogs["income_types"])
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_bootstrap.py -v`
Expected: FALLA (el endpoint `/bootstrap` no existe → 404; o import error del servicio).

- [ ] **Step 3: Crear `backend/app/services/bootstrap_service.py`**

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_network import CreditCardNetwork
from app.models.currency import Currency
from app.models.income_type import IncomeType
from app.models.institution import Institution
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.review_finding_code import ReviewFindingCode
from app.models.user import User


def build_catalogs(db: Session, user: User) -> dict:
    cc = user.country_code
    return {
        "currencies": list(
            db.execute(select(Currency).where(Currency.country_code == cc).order_by(Currency.id)).scalars()
        ),
        "obligation_types": list(
            db.execute(select(ObligationType).where(ObligationType.visible.is_(True)).order_by(ObligationType.id)).scalars()
        ),
        "income_types": list(
            db.execute(select(IncomeType).where(IncomeType.visible.is_(True)).order_by(IncomeType.id)).scalars()
        ),
        "priority_levels": list(
            db.execute(select(PriorityLevel).order_by(PriorityLevel.level)).scalars()
        ),
        "institutions": list(
            db.execute(
                select(Institution).where(Institution.visible.is_(True), Institution.country_code == cc).order_by(Institution.id)
            ).scalars()
        ),
        "review_finding_codes": list(
            db.execute(select(ReviewFindingCode).order_by(ReviewFindingCode.code)).scalars()
        ),
        "credit_card_networks": list(
            db.execute(select(CreditCardNetwork).where(CreditCardNetwork.country_code == cc).order_by(CreditCardNetwork.id)).scalars()
        ),
        "credit_card_item_types": list(
            db.execute(select(CreditCardItemType).order_by(CreditCardItemType.id)).scalars()
        ),
    }
```

- [ ] **Step 4: Crear `backend/app/routers/bootstrap.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.bootstrap import BootstrapResponse, Catalogs
from app.services import bootstrap_service

router = APIRouter(tags=["bootstrap"])


@router.get("/bootstrap", response_model=BootstrapResponse)
def bootstrap(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BootstrapResponse:
    catalogs = bootstrap_service.build_catalogs(db, user)
    return BootstrapResponse(
        version=settings.bootstrap_version,
        catalogs=Catalogs.model_validate(catalogs),
    )
```

- [ ] **Step 5: Montar el router en `backend/app/main.py`**

Agregar `bootstrap` al import de routers y montarlo. El archivo completo queda:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import register_error_handlers
from app.routers import auth, bootstrap, countries, health

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)
app.include_router(health.router)
app.include_router(countries.router)
app.include_router(auth.router)
app.include_router(bootstrap.router)
```

- [ ] **Step 6: Correr y verificar que pasan**

Run: `pytest tests/test_bootstrap.py -v`
Expected: PASAN los 2 tests.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/bootstrap_service.py backend/app/routers/bootstrap.py backend/app/main.py backend/tests/test_bootstrap.py
git commit -m "feat(backend): GET /bootstrap con servicio y tests"
```

---

## Task 4: Verificación + CLAUDE.md

**Files:** Modify `backend/CLAUDE.md`

- [ ] **Step 1: Suite completa**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q`
Expected: pasan todos (los previos 16 + 4 de deps + 2 de bootstrap = 22).

- [ ] **Step 2: Verificación en vivo (opcional, contra `margin` que ya tiene los catálogos sembrados)**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate
uvicorn app.main:app --port 8099 >/tmp/uvicorn_bs.log 2>&1 &
UVPID=$!
TOKEN=$(curl -s --retry 12 --retry-connrefused --retry-delay 1 -X POST http://127.0.0.1:8099/auth/register -H 'Content-Type: application/json' -d '{"email":"bs@margin.uy","password":"12345678"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")
curl -s http://127.0.0.1:8099/bootstrap -H "Authorization: Bearer $TOKEN" | python -m json.tool | head -30
kill $UVPID 2>/dev/null
psql -d margin -c "delete from auth_identities; delete from users;"
```
Expected: imprime `version` + `catalogs` con los 8 catálogos poblados (currencies UY, priority_levels 1–6, etc.). Limpia el usuario de prueba.

- [ ] **Step 3: Actualizar `backend/CLAUDE.md`** — en la sección "Estructura", agregar:

```markdown
- `app/core/deps.py` — `get_current_user` (auth para rutas protegidas: `Depends(get_current_user)`).
```

- [ ] **Step 4: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/CLAUDE.md
git commit -m "docs(backend): CLAUDE.md con get_current_user"
```

---

## Notas de cierre

- Al terminar: `GET /bootstrap` devuelve los 8 catálogos curados y filtrados por país, protegido por `get_current_user`. Queda la base de auth para todos los endpoints protegidos futuros.
- **Cierre:** squash-merge de `feat/bootstrap` → un commit `feat: bootstrap` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** get_current_user + 401 en todos los fallos (T1) ✓; wrapper {version, catalogs} (T2/T3) ✓; 8 catálogos curados (schemas T2, service T3) ✓; filtrado por país (currencies/institutions/credit_card_networks) + visible (obligation/income/institutions) + priority_levels completos (service T3, tests T3) ✓; bootstrap_version de config ✓; tests de auth y endpoint ✓.
- **Placeholders:** ninguno; código completo en cada paso.
- **Consistencia de tipos:** `resolve_user_from_token(token, db)->User` y `get_current_user` consistentes; `build_catalogs` devuelve dict con las 8 claves exactas que `Catalogs` espera; los schemas `*Out` exponen los campos de la sección 4 del spec; `Catalogs.model_validate(dict)` con `from_attributes` en los items lee los objetos ORM.
