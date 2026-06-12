"""add deuda tarjetazo to plan_movement_kind

Revision ID: 1a59f3159ebb
Revises: eab21834b3ee
Create Date: 2026-06-12 04:17:22.938744

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a59f3159ebb'
down_revision: Union[str, None] = 'eab21834b3ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE plan_movement_kind ADD VALUE IF NOT EXISTS 'deuda'")
    op.execute("ALTER TYPE plan_movement_kind ADD VALUE IF NOT EXISTS 'tarjetazo'")


def downgrade() -> None:
    # Postgres no permite DROP VALUE: se recrea el tipo sin deuda/tarjetazo.
    # Falla si existen filas con esos kinds (hay que borrarlas antes de revertir).
    op.execute("ALTER TYPE plan_movement_kind RENAME TO plan_movement_kind_old")
    op.execute("CREATE TYPE plan_movement_kind AS ENUM ('ingreso', 'deuda_informal', 'prestamo')")
    op.execute(
        "ALTER TABLE plan_movements ALTER COLUMN kind TYPE plan_movement_kind "
        "USING kind::text::plan_movement_kind"
    )
    op.execute("DROP TYPE plan_movement_kind_old")
