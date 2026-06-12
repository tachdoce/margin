"""update currency rates from monthly csv

Revision ID: eab21834b3ee
Revises: d2a2d9f5a6e3
Create Date: 2026-06-12 03:08:59.462028

"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eab21834b3ee'
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
