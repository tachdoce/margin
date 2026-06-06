# Backend Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar el backend de Margin corriendo: una app FastAPI con un endpoint `/health` testeado en verde, más los archivos de higiene del proyecto.

**Architecture:** App FastAPI mínima. Un router `health` montado en `main.py`. Config vía pydantic-settings leyendo de `.env` (patrón que después reusa auth). Tests con pytest + TestClient de FastAPI. Sin DB todavía — eso entra con la primera feature que persista (auth).

**Tech Stack:** Python 3.13 (Homebrew, `/opt/homebrew/bin/python3.13`), venv + pip, FastAPI, Uvicorn, pydantic-settings, pytest, httpx.

**Alcance:** Solo el esqueleto del backend. Quedan fuera (planes/specs aparte): la web Vue, SQLAlchemy/Alembic/DB, y la feature `auth`.

---

## Estructura de archivos

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py             # crea la app FastAPI y monta los routers
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py       # Settings (pydantic-settings), lee de .env
│   └── routers/
│       ├── __init__.py
│       └── health.py       # GET /health
├── tests/
│   ├── __init__.py
│   ├── conftest.py         # fixture: TestClient
│   └── test_health.py
├── .env.example            # plantilla de variables (sin secretos reales)
├── requirements.txt        # dependencias
├── pyproject.toml          # config de pytest
└── CLAUDE.md               # contexto del backend para la IA

(raíz del repo)
├── CLAUDE.md               # contexto general para la IA
└── README.md
```

---

## Task 1: Entorno virtual y dependencias

**Files:**
- Create: `backend/requirements.txt`

- [ ] **Step 1: Crear el entorno virtual con Python 3.13**

```bash
cd /Users/tachone/proyectos/margin/backend
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
python --version   # debe imprimir Python 3.13.13
```

- [ ] **Step 2: Escribir `requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic-settings==2.7.1
pytest==8.3.4
httpx==0.28.1
```

- [ ] **Step 3: Instalar dependencias**

Run: `pip install -r requirements.txt`
Expected: termina con "Successfully installed ..." incluyendo fastapi, uvicorn, pytest, httpx.

- [ ] **Step 4: Verificar que el venv quedó ignorado por git**

Run: `git status -s backend/`
Expected: NO aparece `.venv/` (ya está en `.gitignore`). Sí puede aparecer `requirements.txt`.

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/requirements.txt
git commit -m "chore(backend): dependencias base del scaffold"
```

---

## Task 2: Config con pydantic-settings

**Files:**
- Create: `backend/app/__init__.py` (vacío)
- Create: `backend/app/core/__init__.py` (vacío)
- Create: `backend/app/core/config.py`
- Create: `backend/.env.example`

- [ ] **Step 1: Crear los `__init__.py` vacíos**

```bash
cd /Users/tachone/proyectos/margin/backend
touch app/__init__.py app/core/__init__.py
```

- [ ] **Step 2: Escribir `app/core/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Config de la app, leída de variables de entorno / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Margin API"
    environment: str = "development"


settings = Settings()
```

- [ ] **Step 3: Escribir `.env.example`**

```
# Copiar a .env y ajustar. .env NO se commitea (está en .gitignore).
ENVIRONMENT=development
```

- [ ] **Step 4: Verificar que la config carga**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && python -c "from app.core.config import settings; print(settings.app_name, settings.environment)"`
Expected: imprime `Margin API development`

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/__init__.py backend/app/core/ backend/.env.example
git commit -m "feat(backend): config con pydantic-settings"
```

---

## Task 3: Endpoint /health (TDD)

**Files:**
- Create: `backend/app/routers/__init__.py` (vacío)
- Create: `backend/app/routers/health.py`
- Create: `backend/app/main.py`
- Create: `backend/pyproject.toml`
- Create: `backend/tests/__init__.py` (vacío)
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_health.py`

- [ ] **Step 1: Crear `pyproject.toml` con la config de pytest**

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Crear los `__init__.py` vacíos**

```bash
cd /Users/tachone/proyectos/margin/backend
touch app/routers/__init__.py tests/__init__.py
```

- [ ] **Step 3: Escribir el fixture de test en `tests/conftest.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
```

- [ ] **Step 4: Escribir el test que falla en `tests/test_health.py`**

```python
def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}
```

- [ ] **Step 5: Correr el test y verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_health.py -v`
Expected: FALLA al importar `app.main` (todavía no existe) — error de colección tipo `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 6: Escribir el router en `app/routers/health.py`**

```python
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
```

- [ ] **Step 7: Escribir `app/main.py`**

```python
from fastapi import FastAPI

from app.core.config import settings
from app.routers import health

app = FastAPI(title=settings.app_name)
app.include_router(health.router)
```

- [ ] **Step 8: Correr el test y verificar que pasa**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_health.py -v`
Expected: PASA — `test_health_returns_ok PASSED`.

- [ ] **Step 9: Verificar la app a mano (levantarla)**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && uvicorn app.main:app --reload`
Expected: arranca en `http://127.0.0.1:8000`. Abrir `http://127.0.0.1:8000/health` → `{"status":"ok","environment":"development"}`. Abrir `http://127.0.0.1:8000/docs` → la UI de Swagger con el endpoint. Cortar con Ctrl+C.

- [ ] **Step 10: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/ backend/tests/ backend/pyproject.toml
git commit -m "feat(backend): endpoint /health con test"
```

---

## Task 4: Archivos de higiene (CLAUDE.md y README)

**Files:**
- Create: `CLAUDE.md` (raíz)
- Create: `backend/CLAUDE.md`
- Create: `README.md` (raíz)

- [ ] **Step 1: Escribir el `CLAUDE.md` de la raíz**

```markdown
# Margin

App de salud financiera (Uruguay, multi-moneda a futuro).
Producto documentado en Notion: https://app.notion.com/p/Margin-372e504f64bb8033a2a0d65072414bf6
Este repo es **backend + web de pruebas**. La app móvil vive en un repo aparte y consume el contrato OpenAPI.

## Estructura
- `backend/` — FastAPI + Postgres (mío). Ver `backend/CLAUDE.md`.
- `web/` — Vue 3 + Vite, banco de pruebas de endpoints (poco diseño a propósito). [aún no creado]
- `docs/superpowers/specs/` — specs de diseño. `docs/superpowers/plans/` — planes de implementación.

## Convenciones que NO se negocian (detalle en Notion)
- Plata: `numeric`, nunca `float`. Montos numeric(12,2), tasas numeric(5,2), cotizaciones numeric(14,6).
- Tablas/columnas: inglés snake_case. Textos visibles al usuario: español. Enums: valores en español.
- No se persiste lo derivable (saldos, costos), salvo excepción de performance documentada.
- Borrado: hard-delete por defecto; `deleted_at` solo donde se documente con su porqué.
- Decisiones se documentan con su porqué.

## Flujo de trabajo
Spec en `docs/superpowers/specs/` → plan en `docs/superpowers/plans/` → TDD → commit chico → code review → verificación.
```

- [ ] **Step 2: Escribir `backend/CLAUDE.md`**

```markdown
# Backend (Margin)

FastAPI + (a futuro) SQLAlchemy + Alembic + Postgres. Python 3.13.

## Comandos
- Activar entorno: `source .venv/bin/activate`
- Correr la app: `uvicorn app.main:app --reload`
- Correr los tests: `pytest -v`
- Instalar deps: `pip install -r requirements.txt`

## Estructura
- `app/main.py` — crea la app y monta routers.
- `app/core/config.py` — Settings (pydantic-settings, lee de `.env`).
- `app/routers/` — endpoints por subdominio.
- `tests/` — pytest (usa `app.main:app` vía TestClient).
- Próximo: `app/models/` (SQLAlchemy), `app/schemas/` (Pydantic), `app/engines/` (PlanEngine/CashFlowEngine/ReviewEngine), `alembic/`.

## Convenciones (ver también CLAUDE.md raíz y Notion)
- Plata: `numeric`, nunca `float`.
- Tablas/columnas en inglés snake_case; enums con valores en español.
- TDD: test primero, después implementación.
- DB local: bases `margin` y `margin_test` (Postgres 16, Homebrew).
```

- [ ] **Step 3: Escribir `README.md` de la raíz**

```markdown
# Margin

Backend (FastAPI) + web de pruebas (Vue) de la app de salud financiera Margin.
Producto documentado en Notion. Diseño y planes en `docs/superpowers/`.

## Backend — arranque rápido
```bash
cd backend
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs
pytest -v                        # tests
```
```

- [ ] **Step 4: Verificar que los tests siguen pasando**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -v`
Expected: PASA `test_health_returns_ok`.

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add CLAUDE.md backend/CLAUDE.md README.md
git commit -m "docs: CLAUDE.md (raíz + backend) y README"
```

---

## Notas de cierre

- Al terminar las 4 tasks: el backend levanta, `/health` responde, los tests pasan y el repo tiene su andamiaje de contexto para la IA.
- **Siguiente paso sugerido:** brainstorming del spec de `auth` (decisiones: email vs email+Google, vida del token, refresh), que introduce SQLAlchemy + Alembic + la base `margin`.
- En paralelo o después: plan del scaffold de la **web** (Vue) que consume `/health` como primera prueba.
