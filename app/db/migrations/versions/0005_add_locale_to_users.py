"""Add locale column to users table.

Revision ID: 0005_add_locale_to_users
Revises: 0004_production_hardening
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_add_locale_to_users"
down_revision = "0004_production_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locale")
