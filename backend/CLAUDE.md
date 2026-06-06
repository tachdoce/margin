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
- Pydantic serializa `Decimal` como string en JSON (preserva precisión).
