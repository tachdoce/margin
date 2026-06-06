# Backend Foundation + countries — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar el backend de Margin corriendo con su capa de DB completa y la primera tabla real (`countries`) migrada, sembrada (`UY`) y expuesta por un endpoint testeado.

**Architecture:** App FastAPI con config por pydantic-settings, SQLAlchemy 2.0 (engine + session + `Base` declarativa), Alembic para migraciones, y pytest con una base de test aislada (`margin_test`). `countries` es el primer modelo: prueba de punta a punta el pipeline modelo → migración → seed → endpoint → test. Es prerrequisito de `users` (`users.country_code` es FK NOT NULL).

**Tech Stack:** Python 3.13 (`/opt/homebrew/bin/python3.13`), venv + pip, FastAPI, Uvicorn, SQLAlchemy 2.0, Alembic, psycopg2-binary, pydantic-settings, pytest, httpx. Postgres 16 (Homebrew, socket en `/tmp`, auth peer como usuario `tachone`).

**Alcance:** foundation + `countries`. Quedan fuera (plan aparte): `users`, `auth_identities`, registro/login, la web Vue. Diferido: el plan-default que crea el registro (arrastra `currencies`/`plans`).

---

## Estructura de archivos

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py             # app FastAPI + routers
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py       # Settings (pydantic-settings)
│   │   └── db.py           # engine, SessionLocal, Base, get_db
│   ├── models/
│   │   ├── __init__.py     # importa todos los modelos (para Alembic)
│   │   └── country.py      # modelo Country
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── country.py      # CountryRead (Pydantic)
│   └── routers/
│       ├── __init__.py
│       ├── health.py       # GET /health
│       └── countries.py    # GET /countries
├── alembic/                # generado por `alembic init`
│   ├── env.py              # editado: usa settings + Base.metadata
│   └── versions/           # migraciones
├── alembic.ini
├── tests/
│   ├── __init__.py
│   ├── conftest.py         # fixtures: db_session (margin_test) + client
│   ├── test_health.py
│   └── test_countries.py
├── .env.example
├── requirements.txt
├── pyproject.toml          # config de pytest
└── CLAUDE.md
```

---

## Task 1: Entorno virtual y dependencias

**Files:** Create `backend/requirements.txt`

- [ ] **Step 1: Crear el venv con Python 3.13**

```bash
cd /Users/tachone/proyectos/margin/backend
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
python --version   # Python 3.13.13
```

- [ ] **Step 2: Escribir `requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic-settings==2.7.1
sqlalchemy==2.0.36
alembic==1.14.0
psycopg2-binary==2.9.10
pytest==8.3.4
httpx==0.28.1
```

- [ ] **Step 3: Instalar**

Run: `pip install -r requirements.txt`
Expected: "Successfully installed ..." con fastapi, sqlalchemy, alembic, psycopg2-binary, pytest.

- [ ] **Step 4: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/requirements.txt
git commit -m "chore(backend): dependencias base"
```

---

## Task 2: Crear las bases de datos

**Files:** ninguno (operación sobre Postgres)

- [ ] **Step 1: Crear `margin` y `margin_test` (vacías)**

```bash
createdb margin
createdb margin_test
psql -l -tA | cut -d'|' -f1 | grep margin
```
Expected: imprime `margin` y `margin_test`.

---

## Task 3: Config con pydantic-settings

**Files:** Create `app/__init__.py`, `app/core/__init__.py`, `app/core/config.py`, `.env.example`

- [ ] **Step 1: Crear `__init__.py` vacíos**

```bash
cd /Users/tachone/proyectos/margin/backend
touch app/__init__.py app/core/__init__.py
```

- [ ] **Step 2: `app/core/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Config de la app, leída de variables de entorno / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Margin API"
    environment: str = "development"
    # Socket Unix + auth peer (usuario del SO). Sin host = socket por defecto.
    database_url: str = "postgresql+psycopg2:///margin"
    test_database_url: str = "postgresql+psycopg2:///margin_test"


settings = Settings()
```

- [ ] **Step 3: `.env.example`**

```
# Copiar a .env y ajustar. .env NO se commitea.
ENVIRONMENT=development
DATABASE_URL=postgresql+psycopg2:///margin
TEST_DATABASE_URL=postgresql+psycopg2:///margin_test
```

- [ ] **Step 4: Verificar**

Run: `python -c "from app.core.config import settings; print(settings.database_url)"`
Expected: `postgresql+psycopg2:///margin`

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/__init__.py backend/app/core/ backend/.env.example
git commit -m "feat(backend): config con pydantic-settings"
```

---

## Task 4: Capa de DB (SQLAlchemy)

**Files:** Create `app/core/db.py`

- [ ] **Step 1: `app/core/db.py`**

```python
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Base declarativa de todos los modelos."""


def get_db() -> Iterator[Session]:
    """Dependency de FastAPI: una sesión por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 2: Verificar conexión a Postgres**

Run: `python -c "from sqlalchemy import text; from app.core.db import engine; print(engine.connect().execute(text('select 1')).scalar())"`
Expected: imprime `1` (conecta a `margin` por socket).

- [ ] **Step 3: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/core/db.py
git commit -m "feat(backend): capa de DB con SQLAlchemy"
```

---

## Task 5: Endpoint /health (TDD)

**Files:** Create `app/routers/__init__.py`, `app/routers/health.py`, `app/main.py`, `pyproject.toml`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_health.py`

- [ ] **Step 1: `pyproject.toml`**

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: `__init__.py` vacíos**

```bash
cd /Users/tachone/proyectos/margin/backend
touch app/routers/__init__.py tests/__init__.py
```

- [ ] **Step 3: `tests/conftest.py` (fixtures base)**

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.db import Base, get_db
from app.main import app
from app import models as _models  # noqa: F401  (registra modelos sin pisar el nombre `app`)

test_engine = create_engine(settings.test_database_url)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


@pytest.fixture
def db_session() -> Session:
    """Sesión sobre margin_test; cada test corre en una transacción que se revierte."""
    Base.metadata.create_all(bind=test_engine)
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()
```

> Nota: `tests/conftest.py` importa `app.models`, que aún no existe hasta Task 7. Por eso primero creamos un `app/models/__init__.py` vacío en este task (Step 4) para que las importaciones no rompan.

- [ ] **Step 4: `app/models/__init__.py` vacío (placeholder hasta Task 7)**

```bash
cd /Users/tachone/proyectos/margin/backend
mkdir -p app/models && touch app/models/__init__.py
```

- [ ] **Step 5: Test que falla `tests/test_health.py`**

```python
def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}
```

- [ ] **Step 6: Correr y verificar que falla**

Run: `pytest tests/test_health.py -v`
Expected: FALLA por no poder importar `app.main` (todavía no existe).

- [ ] **Step 7: `app/routers/health.py`**

```python
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
```

- [ ] **Step 8: `app/main.py`**

```python
from fastapi import FastAPI

from app.core.config import settings
from app.routers import health

app = FastAPI(title=settings.app_name)
app.include_router(health.router)
```

- [ ] **Step 9: Correr y verificar que pasa**

Run: `pytest tests/test_health.py -v`
Expected: PASA `test_health_returns_ok`.

- [ ] **Step 10: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/ backend/tests/ backend/pyproject.toml
git commit -m "feat(backend): endpoint /health con test y harness de DB de test"
```

---

## Task 6: Alembic

**Files:** Create `alembic/` (init), Modify `alembic/env.py`, `alembic.ini`

- [ ] **Step 1: Inicializar Alembic**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic init alembic`
Expected: crea `alembic/`, `alembic/env.py`, `alembic.ini`.

- [ ] **Step 2: Editar `alembic/env.py` para usar nuestra config y metadata**

Reemplazar el bloque de `target_metadata = None` y la lectura de URL por:

```python
# (cerca del tope, después de los imports que ya trae)
from app.core.config import settings
from app.core.db import Base
import app.models  # noqa: F401  (registra los modelos)

config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata
```

- [ ] **Step 3: Verificar que Alembic conecta (sin migraciones todavía)**

Run: `alembic current`
Expected: corre sin error; no imprime ninguna revisión (head vacío).

- [ ] **Step 4: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/alembic backend/alembic.ini
git commit -m "chore(backend): configurar Alembic con settings y Base.metadata"
```

---

## Task 7: Modelo `countries` + migración + seed

**Files:** Create `app/models/country.py`, Modify `app/models/__init__.py`, Create migración en `alembic/versions/`

- [ ] **Step 1: `app/models/country.py`**

```python
from decimal import Decimal

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Country(Base):
    __tablename__ = "countries"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default="0")
```

- [ ] **Step 2: Registrar el modelo en `app/models/__init__.py`**

```python
from app.models.country import Country  # noqa: F401
```

- [ ] **Step 3: Autogenerar la migración**

Run: `alembic revision --autogenerate -m "create countries"`
Expected: crea un archivo en `alembic/versions/` cuyo `upgrade()` contiene `op.create_table('countries', ...)` con las columnas `code`, `name`, `visible`, `vat_rate`.

- [ ] **Step 4: Agregar el seed `UY` al `upgrade()` de esa migración**

Al final de `upgrade()`, después del `create_table`, agregar:

```python
    op.bulk_insert(
        sa.table(
            "countries",
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("visible", sa.Boolean),
            sa.column("vat_rate", sa.Numeric),
        ),
        [{"code": "UY", "name": "Uruguay", "visible": True, "vat_rate": 22.00}],
    )
```

- [ ] **Step 5: Aplicar la migración a `margin`**

Run: `alembic upgrade head`
Expected: aplica la migración sin error.

- [ ] **Step 6: Verificar el seed en la base**

Run: `psql -d margin -tAc "select code, name, vat_rate from countries;"`
Expected: `UY|Uruguay|22.00`

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models backend/alembic/versions
git commit -m "feat(backend): tabla countries con seed UY"
```

---

## Task 8: Endpoint GET /countries (TDD)

**Files:** Create `app/schemas/__init__.py`, `app/schemas/country.py`, `app/routers/countries.py`, `tests/test_countries.py`, Modify `app/main.py`

- [ ] **Step 1: `app/schemas/__init__.py` vacío + `app/schemas/country.py`**

```bash
cd /Users/tachone/proyectos/margin/backend && touch app/schemas/__init__.py
```

```python
# app/schemas/country.py
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CountryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    visible: bool
    vat_rate: Decimal
```

- [ ] **Step 2: Test que falla `tests/test_countries.py`**

```python
from decimal import Decimal

from app.models.country import Country


def test_list_countries_returns_visible(client, db_session):
    db_session.add(Country(code="UY", name="Uruguay", visible=True, vat_rate=Decimal("22.00")))
    db_session.flush()

    response = client.get("/countries")

    assert response.status_code == 200
    data = response.json()
    uy = next(c for c in data if c["code"] == "UY")
    assert uy["name"] == "Uruguay"
    assert uy["visible"] is True
    assert Decimal(str(uy["vat_rate"])) == Decimal("22.00")
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `pytest tests/test_countries.py -v`
Expected: FALLA (404 o import error: el router `/countries` no existe).

- [ ] **Step 4: `app/routers/countries.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.country import Country
from app.schemas.country import CountryRead

router = APIRouter(prefix="/countries", tags=["countries"])


@router.get("", response_model=list[CountryRead])
def list_countries(db: Session = Depends(get_db)) -> list[Country]:
    return list(db.execute(select(Country).where(Country.visible.is_(True))).scalars())
```

- [ ] **Step 5: Montar el router en `app/main.py`**

```python
from fastapi import FastAPI

from app.core.config import settings
from app.routers import countries, health

app = FastAPI(title=settings.app_name)
app.include_router(health.router)
app.include_router(countries.router)
```

- [ ] **Step 6: Correr y verificar que pasa**

Run: `pytest -v`
Expected: PASAN `test_health_returns_ok` y `test_list_countries_returns_visible`.

- [ ] **Step 7: Verificar a mano**

Run: `uvicorn app.main:app --reload` y abrir `http://127.0.0.1:8000/countries`
Expected: `[{"code":"UY","name":"Uruguay","visible":true,"vat_rate":"22.00"}]`. Cortar con Ctrl+C.

- [ ] **Step 8: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/ backend/tests/
git commit -m "feat(backend): endpoint GET /countries con test"
```

---

## Task 9: Archivos de higiene (CLAUDE.md y README)

**Files:** Create `CLAUDE.md` (raíz), `backend/CLAUDE.md`, `README.md` (raíz)

- [ ] **Step 1: `CLAUDE.md` raíz**

```markdown
# Margin

App de salud financiera (Uruguay, multi-moneda a futuro).
Producto en Notion: https://app.notion.com/p/Margin-372e504f64bb8033a2a0d65072414bf6
Este repo es **backend + web de pruebas**. La app móvil vive aparte y consume el contrato OpenAPI.

## Estructura
- `backend/` — FastAPI + SQLAlchemy + Alembic + Postgres (mío). Ver `backend/CLAUDE.md`.
- `web/` — Vue 3 + Vite, banco de pruebas (poco diseño a propósito). [aún no creado]
- `docs/superpowers/specs/` — specs de diseño. `docs/superpowers/plans/` — planes.

## Convenciones que NO se negocian (detalle en Notion)
- Plata: `numeric`, nunca `float` (en Python: `Decimal`). Montos numeric(12,2), tasas numeric(5,2).
- Tablas/columnas: inglés snake_case. Textos al usuario: español. Enums: valores en español
  (excepción: `auth_provider` = `email`/`google`, nombres técnicos).
- No se persiste lo derivable, salvo excepción de performance documentada.
- Borrado: hard-delete por defecto; `deleted_at` solo donde se documente (ej. `users`).

## Flujo de trabajo
Spec en `docs/superpowers/specs/` → plan en `docs/superpowers/plans/` → TDD → commit chico → review → verificación.
```

- [ ] **Step 2: `backend/CLAUDE.md`**

```markdown
# Backend (Margin)

FastAPI + SQLAlchemy 2.0 + Alembic + Postgres 16. Python 3.13.

## Comandos
- Entorno: `source .venv/bin/activate`
- App: `uvicorn app.main:app --reload`  (http://127.0.0.1:8000/docs)
- Tests: `pytest -v`  (usa la base `margin_test`)
- Migración nueva: `alembic revision --autogenerate -m "msg"` → revisar → `alembic upgrade head`
- Bases locales: `margin` (dev) y `margin_test` (tests), socket Unix, usuario `tachone`.

## Estructura
- `app/main.py` — app + routers.
- `app/core/config.py` — Settings (pydantic-settings).
- `app/core/db.py` — engine, SessionLocal, Base, get_db.
- `app/models/` — SQLAlchemy (registrar cada modelo en `__init__.py` para Alembic).
- `app/schemas/` — Pydantic (request/response).
- `app/routers/` — endpoints por subdominio.
- `alembic/` — migraciones.
- `tests/` — pytest (fixtures `db_session` + `client` en conftest).

## Convenciones (ver CLAUDE.md raíz y Notion)
- Plata/tasas: `Numeric` + `Decimal`, nunca float.
- TDD: test primero. Cada modelo nuevo se registra en `app/models/__init__.py`.
```

- [ ] **Step 3: `README.md` raíz**

```markdown
# Margin

Backend (FastAPI) + web de pruebas (Vue) de la app de salud financiera Margin.
Diseño y planes en `docs/superpowers/`.

## Backend — arranque
```bash
cd backend
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
createdb margin && createdb margin_test   # solo la primera vez
alembic upgrade head
uvicorn app.main:app --reload             # http://127.0.0.1:8000/docs
pytest -v
```
```

- [ ] **Step 4: Verificar que todo sigue verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -v`
Expected: PASAN los dos tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add CLAUDE.md backend/CLAUDE.md README.md
git commit -m "docs: CLAUDE.md (raíz + backend) y README"
```

---

## Notas de cierre

- Al terminar: backend levanta, `/health` y `/countries` responden, migración + seed `UY` aplicados, tests verdes, y el andamiaje de contexto para la IA en su lugar.
- **Siguiente plan:** `users` + `auth_identities` + endpoints de registro/login (JWT, hash bcrypt). `countries` ya queda como FK disponible para `users.country_code`.
- **Diferido (documentado):** el registro completo crea además un `plan` default (deriva moneda de `currencies`) — entra con el subdominio de flujo de dinero.
```

## Self-review (writing-plans)

- **Cobertura:** countries (tabla+seed+endpoint) ✓; foundation DB/Alembic/test harness ✓; convenciones de plata=Decimal reflejadas en el modelo ✓. `users`/`auth` explícitamente en plan aparte.
- **Placeholders:** sin TBD/TODO en pasos; todo paso de código trae el código.
- **Consistencia de tipos:** `Country(code,name,visible,vat_rate:Decimal)` igual en modelo, schema y test; `get_db`/`Base`/`SessionLocal` consistentes entre `db.py`, `conftest.py` y `env.py`.
