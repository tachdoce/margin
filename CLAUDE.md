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

**Git (todo el equipo):** trabajar en rama `feat/<nombre>` con commits chicos; integrar a `main` con
**squash-merge** (un commit por feature). Detalle en `docs/superpowers/specs/2026-06-06-estructura-y-flujo-de-trabajo-design.md` (sección 6).
