"""remove priority_levels

Revision ID: 2a2a7fdc153f
Revises: 1a59f3159ebb
Create Date: 2026-06-14 19:04:02.820890

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a2a7fdc153f'
down_revision: Union[str, None] = '1a59f3159ebb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM obligation_types WHERE code = 'adelanto_sueldo'")
    # En Postgres, DROP COLUMN elimina sola la FK de esa columna.
    op.drop_column("obligations", "priority_level")
    op.drop_column("obligation_types", "default_priority_level")
    op.drop_table("priority_levels")


def downgrade() -> None:
    # best-effort: recrea la tabla y las columnas (sin restaurar FK/NOT NULL ni el seed)
    op.create_table(
        "priority_levels",
        sa.Column("level", sa.SmallInteger(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
    )
    op.add_column("obligation_types", sa.Column("default_priority_level", sa.SmallInteger(), nullable=True))
    op.add_column("obligations", sa.Column("priority_level", sa.SmallInteger(), nullable=True))
