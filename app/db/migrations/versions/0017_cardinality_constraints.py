"""Add min_select and max_select cardinality to characteristic_assignments.

Revision ID: 0017_cardinality_constraints
Revises: 0016_product_configurator
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa

revision = "0017_cardinality_constraints"
down_revision = "0016_product_configurator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "characteristic_assignments",
        sa.Column("min_select", sa.Integer, nullable=True),
    )
    op.add_column(
        "characteristic_assignments",
        sa.Column("max_select", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("characteristic_assignments", "max_select")
    op.drop_column("characteristic_assignments", "min_select")
