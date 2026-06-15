"""add priority fields

Revision ID: 06e6b498b042
Revises: 2a2a7fdc153f
Create Date: 2026-06-15 01:18:37.397544

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '06e6b498b042'
down_revision: Union[str, None] = '2a2a7fdc153f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    payment_rule = postgresql.ENUM(
        "ninguno", "minimo", "total", "mensual", name="payment_rule", create_type=False
    )
    payment_rule.create(op.get_bind(), checkfirst=True)
    op.add_column("obligations", sa.Column("payment_rule", payment_rule, nullable=False, server_default="ninguno"))
    op.add_column("obligations", sa.Column("priority", sa.SmallInteger(), nullable=True))
    op.add_column("obligations", sa.Column("monthly_paydown_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("obligations", sa.Column("priority_open_debt", sa.SmallInteger(), nullable=True))
    op.add_column("credit_cards", sa.Column("payment_rule", payment_rule, nullable=False, server_default="ninguno"))
    op.add_column("credit_cards", sa.Column("priority", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("credit_cards", "priority")
    op.drop_column("credit_cards", "payment_rule")
    op.drop_column("obligations", "priority_open_debt")
    op.drop_column("obligations", "monthly_paydown_amount")
    op.drop_column("obligations", "priority")
    op.drop_column("obligations", "payment_rule")
    postgresql.ENUM(name="payment_rule").drop(op.get_bind(), checkfirst=True)
