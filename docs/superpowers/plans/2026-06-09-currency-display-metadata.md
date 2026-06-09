# Currency Display Metadata — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar dos columnas de metadata de display (`symbol`, `display_decimals`) a `currencies` y exponerlas en el catálogo del bootstrap.

**Architecture:** Cambio aditivo en una tabla de catálogo existente. Las columnas son atributos intrínsecos de cada moneda (relación 1:1 → columnas, no tabla aparte). `display_decimals` es solo display: el storage de montos sigue `numeric(12,2)`. El backend solo persiste y expone; el formateo es del cliente.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · Postgres 16 · pytest.

**Spec:** [docs/superpowers/specs/2026-06-09-currency-display-metadata-design.md](../specs/2026-06-09-currency-display-metadata-design.md)

**Contexto del proyecto:** activar venv (`source .venv/bin/activate`) desde `backend/`. Tests: `pytest`. Los tests usan `create_all` + fixtures (NO corren migraciones); por eso los valores reales de las columnas se pasan al construir `Currency(...)` en las fixtures.

---

### Task 1: Columnas en el modelo + exposición en el catálogo (TDD)

**Files:**
- Test: `backend/tests/test_bootstrap.py` (modificar `_seed_catalogs` y `test_bootstrap_returns_catalogs`)
- Modify: `backend/app/models/currency.py`
- Modify: `backend/app/schemas/bootstrap.py:8-12` (`CurrencyOut`)

- [ ] **Step 1: Escribir el test que falla**

En `backend/tests/test_bootstrap.py`, en `_seed_catalogs`, cambiar la fila del Peso (id=1) para que incluya los nuevos campos:

```python
        Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True,
                 symbol="$", display_decimals=0),
```

Y en `test_bootstrap_returns_catalogs`, después de la línea que asserta `peso["allowed_in_credit_card"]`, agregar:

```python
    assert peso["symbol"] == "$"
    assert peso["display_decimals"] == 0
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run (desde `backend/`, con venv activo): `pytest tests/test_bootstrap.py::test_bootstrap_returns_catalogs -v`
Expected: FAIL — `TypeError: 'symbol' is an invalid keyword argument for Currency` (el modelo aún no tiene las columnas).

- [ ] **Step 3: Agregar las columnas al modelo**

En `backend/app/models/currency.py` (el import `from sqlalchemy import Boolean, ForeignKey, SmallInteger, String` ya trae `SmallInteger` y `String`, no hace falta tocarlo). Agregar dentro de la clase `Currency`, después de `allowed_in_credit_card`:

```python
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, server_default="")
    display_decimals: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="2")
```

- [ ] **Step 4: Exponer los campos en `CurrencyOut`**

En `backend/app/schemas/bootstrap.py`, en la clase `CurrencyOut`, agregar después de `allowed_in_credit_card`:

```python
    symbol: str
    display_decimals: int
```

- [ ] **Step 5: Correr el test para verificar que pasa**

Run: `pytest tests/test_bootstrap.py -v`
Expected: PASS (los dos tests de bootstrap).

- [ ] **Step 6: Correr la suite completa (no romper nada)**

Run: `pytest`
Expected: PASS. Las demás fixtures construyen `Currency(...)` sin `symbol`/`display_decimals`; el `server_default` cubre la inserción en DB, así que no rompen.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/currency.py backend/app/schemas/bootstrap.py backend/tests/test_bootstrap.py
git commit -m "feat: symbol y display_decimals en currencies (modelo + catálogo)"
```

---

### Task 2: Migración con backfill de las 5 monedas UY

**Files:**
- Create: `backend/alembic/versions/<rev>_currencies_display_metadata.py` (lo genera Alembic)

- [ ] **Step 1: Autogenerar la migración**

Run (desde `backend/`, con venv activo y la DB `margin` al día con `alembic upgrade head`):

```bash
alembic revision --autogenerate -m "currencies display metadata"
```

Expected: crea un archivo en `alembic/versions/` con dos `op.add_column` para `symbol` y `display_decimals`.

- [ ] **Step 2: Revisar y completar el `upgrade` con el backfill**

Abrir el archivo generado. El `upgrade()` debe quedar así (verificar los dos `add_column`; agregar el bloque de backfill después):

```python
def upgrade() -> None:
    op.add_column('currencies', sa.Column('symbol', sa.String(length=10), nullable=False, server_default=''))
    op.add_column('currencies', sa.Column('display_decimals', sa.SmallInteger(), nullable=False, server_default='2'))

    currencies = sa.table(
        "currencies",
        sa.column("id", sa.SmallInteger),
        sa.column("symbol", sa.String),
        sa.column("display_decimals", sa.SmallInteger),
    )
    for _id, _symbol, _decimals in [
        (1, "$", 0),
        (2, "U$S", 2),
        (3, "U$S", 2),
        (4, "UI", 2),
        (5, "UR", 2),
    ]:
        op.execute(
            currencies.update().where(currencies.c.id == _id).values(symbol=_symbol, display_decimals=_decimals)
        )
```

- [ ] **Step 3: Verificar el `downgrade`**

Confirmar que `downgrade()` solo dropea las dos columnas (nunca la tabla):

```python
def downgrade() -> None:
    op.drop_column('currencies', 'display_decimals')
    op.drop_column('currencies', 'symbol')
```

- [ ] **Step 4: Aplicar la migración a la DB de dev**

Run: `alembic upgrade head`
Expected: `Running upgrade ... -> <rev>, currencies display metadata`. Sin errores.

- [ ] **Step 5: Verificar el backfill**

Run: `psql margin -c "SELECT id, name, symbol, display_decimals FROM currencies ORDER BY id;"`
Expected: Peso → `$ / 0`; Dólar compra → `U$S / 2`; Dólar → `U$S / 2`; Unidad Indexada → `UI / 2`; Unidad Reajustable → `UR / 2`.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat: migración currencies display metadata (+ backfill UY)"
```

---

## Cierre

- Suite verde + migración aplicada → la rama `feat/currency-display-metadata` queda lista para **squash-merge** a `main`.
- **Notion:** actualizar `BD → currencies` con las dos columnas nuevas (`symbol`, `display_decimals`).
- Usar la skill `superpowers:requesting-code-review` antes de mergear.
