"""Production hardening: nullable User.tenant_id for multi-org support.

P0-9: Makes User.tenant_id nullable so users can belong to multiple
tenants via TenantMembership. The tenant_id column is retained as a
default/primary tenant for backward compatibility.

Revision ID: a007_production_hardening
Revises: a006_gold_standard
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa

revision = "a007_production_hardening"
down_revision = "a006_gold_standard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make User.tenant_id nullable to support multi-org users (P0-9).
    # Existing users keep their tenant_id; new users joining multiple
    # orgs can have tenant_id=NULL with memberships in TenantMembership.
    op.alter_column(
        "users",
        "tenant_id",
        existing_type=sa.dialects.postgresql.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    # Revert: make tenant_id NOT NULL again.
    # WARNING: This will fail if any users have NULL tenant_id.
    op.alter_column(
        "users",
        "tenant_id",
        existing_type=sa.dialects.postgresql.UUID(),
        nullable=False,
    )
