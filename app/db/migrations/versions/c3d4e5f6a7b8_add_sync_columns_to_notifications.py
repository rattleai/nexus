"""Add sync columns to notifications table

Revision ID: c3d4e5f6a7b8
Revises: a2b3c4d5e6f7
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("sync_version", sa.BigInteger, nullable=False, server_default=sa.text("0")))
    op.add_column("notifications", sa.Column("sync_checksum", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "sync_checksum")
    op.drop_column("notifications", "sync_version")
