"""Add MFA support columns to users table.

Adds mfa_enabled boolean flag to track whether a user has enrolled
in multi-factor authentication (WebAuthn-based).

Revision ID: 0010_mfa_support
Revises: 0009_parallel_tool_execution
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_mfa_support"
down_revision = "0009_parallel_tool_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_enabled")
