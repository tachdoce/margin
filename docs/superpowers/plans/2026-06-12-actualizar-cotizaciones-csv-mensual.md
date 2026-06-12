# Actualizar cotizaciones desde CSV mensual — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sobrescribir las cotizaciones proyectadas de `currency_rates` para 2026-06 → 2027-12 con los valores mensuales del CSV, expandidos a todos los días de cada mes, vía una migración Alembic de solo datos.

**Architecture:** Migración Alembic que NO toca el schema. `upgrade()` borra el rango 2026-06-01 → 2027-12-31 y reinserta los días expandidos desde un literal mensual embebido. `downgrade()` reinserta los valores planos previos para el mismo rango. Los meses 2026-04/05 quedan intactos.

**Tech Stack:** Alembic, SQLAlchemy Core (`op.bulk_insert`, `op.execute`), `Decimal`. Sin cambios de modelo, schema, ni código de app.

**Verificación:** Manual sobre la base dev `margin` (el harness de tests usa `create_all` y no corre migraciones — ver spec). Sin test automatizado, igual que el seed original `44c310780edb`.

**Spec:** `docs/superpowers/specs/2026-06-12-actualizar-cotizaciones-csv-mensual-design.md`

---

### Task 1: Migración de datos `update_currency_rates_from_monthly_csv`

**Files:**
- Create: `backend/alembic/versions/<rev>_update_currency_rates_from_monthly_csv.py` (Alembic genera `<rev>`)

**Contexto que el implementador necesita:**
- Head actual de Alembic: `d2a2d9f5a6e3`. La nueva migración debe tener `down_revision = 'd2a2d9f5a6e3'` (Alembic lo pone solo al generar el skeleton).
- Base dev: `margin` (socket Unix, usuario `tachone`). Se accede con `psql margin -c "..."`.
- Mapeo columna CSV → `currency_id`: `dolar compra`→2, `dolar venta`→3, `UI`→4, `UR`→5. Peso (id 1) **no** lleva fila.
- Patrón de referencia (seed original con `bulk_insert` + expansión por día): `backend/alembic/versions/44c310780edb_create_currency_rates.py:33-55`.
- Trabajar desde `backend/` con el venv activo: `cd backend && source .venv/bin/activate`.

---

- [ ] **Step 1: Generar el skeleton de la migración**

```bash
cd backend && source .venv/bin/activate
alembic revision -m "update currency rates from monthly csv"
```

Expected: crea `backend/alembic/versions/<rev>_update_currency_rates_from_monthly_csv.py` con `down_revision = 'd2a2d9f5a6e3'`. Anotá el `<rev>` generado. **Verificá** que `down_revision` sea exactamente `'d2a2d9f5a6e3'`; si no, corregilo a mano.

- [ ] **Step 2: Reemplazar el cuerpo de la migración con esta implementación completa**

Sobrescribí TODO el archivo generado (conservando el `revision`/`down_revision` que generó Alembic en las líneas de identificadores) con este contenido. **Importante:** dejá la línea `revision: str = '<rev>'` con el valor que generó Alembic; solo se muestra como `'<rev>'` acá.

```python
"""update currency rates from monthly csv

Revision ID: <rev>
Revises: d2a2d9f5a6e3
Create Date: <generada por alembic>

"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '<rev>'
down_revision: Union[str, None] = 'd2a2d9f5a6e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RANGE_START = "2026-06-01"
RANGE_END = "2027-12-31"

# Valores mensuales del CSV proyeccion_indicadores_2026_2027.csv.
# Mapeo: dolar compra -> 2, dolar venta -> 3, UI -> 4, UR -> 5. Peso (id 1) no lleva fila.
MONTHLY = {
    "2026-06": {2: "40.40", 3: "41.40", 4: "6.57", 5: "1921.36"},
    "2026-07": {2: "40.42", 3: "41.42", 4: "6.60", 5: "1932.97"},
    "2026-08": {2: "40.44", 3: "41.44", 4: "6.62", 5: "1944.66"},
    "2026-09": {2: "40.46", 3: "41.46", 4: "6.65", 5: "1956.41"},
    "2026-10": {2: "40.48", 3: "41.48", 4: "6.67", 5: "1968.24"},
    "2026-11": {2: "40.49", 3: "41.49", 4: "6.70", 5: "1980.14"},
    "2026-12": {2: "40.50", 3: "41.50", 4: "6.72", 5: "1992.11"},
    "2027-01": {2: "40.61", 3: "41.61", 4: "6.75", 5: "2004.15"},
    "2027-02": {2: "40.71", 3: "41.71", 4: "6.77", 5: "2016.27"},
    "2027-03": {2: "40.82", 3: "41.82", 4: "6.80", 5: "2028.45"},
    "2027-04": {2: "40.93", 3: "41.93", 4: "6.83", 5: "2040.72"},
    "2027-05": {2: "41.03", 3: "42.03", 4: "6.85", 5: "2053.05"},
    "2027-06": {2: "41.14", 3: "42.14", 4: "6.88", 5: "2065.46"},
    "2027-07": {2: "41.25", 3: "42.25", 4: "6.91", 5: "2077.95"},
    "2027-08": {2: "41.36", 3: "42.36", 4: "6.93", 5: "2090.51"},
    "2027-09": {2: "41.47", 3: "42.47", 4: "6.96", 5: "2103.15"},
    "2027-10": {2: "41.58", 3: "42.58", 4: "6.98", 5: "2115.86"},
    "2027-11": {2: "41.69", 3: "42.69", 4: "7.01", 5: "2128.65"},
    "2027-12": {2: "41.80", 3: "42.80", 4: "7.04", 5: "2141.52"},
}

# Valores planos previos a esta migración (seed 44c310780edb), para el downgrade.
PREVIOUS_FLAT = {2: "39", 3: "41", 4: "6.55", 5: "1921.36"}


def _table():
    return sa.table(
        "currency_rates",
        sa.column("currency_id", sa.SmallInteger),
        sa.column("rate_date", sa.Date),
        sa.column("value", sa.Numeric),
        sa.column("is_projected", sa.Boolean),
    )


def _month_days(year: int, month: int):
    """Itera cada fecha del mes (year, month)."""
    d = date(year, month, 1)
    while d.year == year and d.month == month:
        yield d
        d += timedelta(days=1)


def _expand_monthly(monthly):
    """dict {'YYYY-MM': {currency_id: value}} -> filas diarias para bulk_insert."""
    rows = []
    for ym, values in monthly.items():
        year, month = int(ym[:4]), int(ym[5:7])
        for d in _month_days(year, month):
            for currency_id, value in values.items():
                rows.append(
                    {
                        "currency_id": currency_id,
                        "rate_date": d,
                        "value": Decimal(value),
                        "is_projected": True,
                    }
                )
    return rows


def _expand_flat(flat, start: date, end: date):
    """dict {currency_id: value} repetido todos los días de [start, end]."""
    rows = []
    d = start
    while d <= end:
        for currency_id, value in flat.items():
            rows.append(
                {
                    "currency_id": currency_id,
                    "rate_date": d,
                    "value": Decimal(value),
                    "is_projected": True,
                }
            )
        d += timedelta(days=1)
    return rows


def upgrade() -> None:
    op.execute(
        f"DELETE FROM currency_rates "
        f"WHERE rate_date BETWEEN '{RANGE_START}' AND '{RANGE_END}'"
    )
    op.bulk_insert(_table(), _expand_monthly(MONTHLY))


def downgrade() -> None:
    op.execute(
        f"DELETE FROM currency_rates "
        f"WHERE rate_date BETWEEN '{RANGE_START}' AND '{RANGE_END}'"
    )
    op.bulk_insert(
        _table(),
        _expand_flat(PREVIOUS_FLAT, date(2026, 6, 1), date(2027, 12, 31)),
    )
```

- [ ] **Step 3: Aplicar la migración a la base dev**

```bash
alembic upgrade head
```

Expected: corre sin error y muestra `Running upgrade d2a2d9f5a6e3 -> <rev>, update currency rates from monthly csv`.

- [ ] **Step 4: Spot-check de valores (verificación manual del spec)**

Corré cada query y confirmá el resultado esperado:

```bash
psql margin -tA -c "SELECT value FROM currency_rates WHERE currency_id=3 AND rate_date='2026-06-15'"
```
Expected: `41.400000`

```bash
psql margin -tA -c "SELECT value FROM currency_rates WHERE currency_id=4 AND rate_date='2027-12-01'"
```
Expected: `7.040000`

```bash
psql margin -tA -c "SELECT COUNT(DISTINCT value) FROM currency_rates WHERE currency_id=2 AND rate_date BETWEEN '2027-03-01' AND '2027-03-31'"
```
Expected: `1` (uniformidad mensual)

```bash
psql margin -tA -c "SELECT value FROM currency_rates WHERE currency_id=2 AND rate_date='2026-07-15'"
```
Expected: `40.420000` (distinto del mes anterior → cambio entre meses)

```bash
psql margin -tA -c "SELECT value FROM currency_rates WHERE currency_id=3 AND rate_date='2026-05-15'"
```
Expected: `41.000000` (mes fuera del CSV intacto)

```bash
psql margin -tA -c "SELECT COUNT(*) FROM currency_rates WHERE currency_id=1 AND rate_date BETWEEN '2026-06-01' AND '2027-12-31'"
```
Expected: `0` (Peso sin fila)

```bash
psql margin -tA -c "SELECT COUNT(*) FROM currency_rates WHERE currency_id=4 AND rate_date BETWEEN '2027-02-01' AND '2027-02-28'"
```
Expected: `28` (febrero 2027 expandido correctamente, sin 29)

- [ ] **Step 5: Verificar reversibilidad**

```bash
alembic downgrade -1
psql margin -tA -c "SELECT value FROM currency_rates WHERE currency_id=3 AND rate_date='2026-06-15'"
```
Expected: `41.000000` (volvió al valor plano previo)

```bash
psql margin -tA -c "SELECT value FROM currency_rates WHERE currency_id=3 AND rate_date='2026-05-15'"
```
Expected: `41.000000` (abril/mayo siguen intactos tras el downgrade)

```bash
alembic upgrade head
psql margin -tA -c "SELECT value FROM currency_rates WHERE currency_id=3 AND rate_date='2026-06-15'"
```
Expected: `41.400000` (re-aplicado el CSV)

- [ ] **Step 6: Commit**

El spec y el plan ya están commiteados por la tab de diseño; acá solo se commitea la migración.

```bash
git add backend/alembic/versions/*_update_currency_rates_from_monthly_csv.py
git commit -m "feat: actualiza cotizaciones 2026-06→2027-12 desde CSV mensual"
```

---

## Notas de cierre

- No hay cambios en modelos, schemas, routers ni servicios. El consumidor (`cash_flow_entry_service`) sigue joineando por `(currency_id, rate_date)` sin cambios.
- La base de tests no corre migraciones, así que `pytest` no se ve afectado por este cambio (no hay test nuevo que correr). Igual conviene correr `pytest -q` una vez para confirmar que nada se rompió.
