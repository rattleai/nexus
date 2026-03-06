"""Add missing composite indexes for join-heavy queries.

Covers: tenant membership lookups by (user_id, tenant_id),
audit log resource history queries.

Revision ID: a004_composite_indexes
Revises: a003_token_hashes
Create Date: 2026-03-06
"""

from alembic import op

revision = "a004_composite_indexes"
down_revision = "a003_token_hashes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # TenantMembership: fast lookup by (user_id, tenant_id) for role checks
    op.create_index(
        "ix_tenant_memberships_user_tenant",
        "tenant_memberships",
        ["user_id", "tenant_id"],
        unique=True,
    )

    # AuditLog: resource history queries (e.g. all events for a specific resource)
    op.create_index(
        "ix_audit_logs_resource",
        "audit_logs",
        ["resource_type", "resource_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_resource", table_name="audit_logs")
    op.drop_index("ix_tenant_memberships_user_tenant", table_name="tenant_memberships")
