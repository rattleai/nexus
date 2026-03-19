"""Add RLS policies to GDPR tables (consents, data_subject_requests, data_retention_policies).

Revision ID: 0011_gdpr_rls_policies
Revises: 0010_mfa_support
Create Date: 2026-03-19
"""

from alembic import op
from sqlalchemy import text

revision = "0011_gdpr_rls_policies"
down_revision = "0010_mfa_support"
branch_labels = None
depends_on = None

TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# GDPR tables from migration 0006 that were missed by migration 0007
GDPR_TABLES = [
    "consents",
    "data_subject_requests",
    "data_retention_policies",
]


def upgrade() -> None:
    # Add FK constraints to GDPR tables
    op.create_foreign_key(
        "fk_consents_tenant_id", "consents", "tenants", ["tenant_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_data_subject_requests_tenant_id", "data_subject_requests", "tenants", ["tenant_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_data_retention_policies_tenant_id", "data_retention_policies", "tenants", ["tenant_id"], ["id"]
    )

    # Add unique partial index on idempotency_key for agent_instances
    op.create_index(
        "ix_agent_instances_idempotency",
        "agent_instances",
        ["tenant_id", "definition_id", "idempotency_key"],
        unique=True,
        postgresql_where=text("idempotency_key IS NOT NULL"),
    )

    for table in GDPR_TABLES:
        # Enable row-level security on the table
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

        # Create tenant isolation policy with USING + WITH CHECK
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = {TENANT_SETTING}) "
            f"WITH CHECK (tenant_id = {TENANT_SETTING})"
        )

        # Force RLS even for table owners (defense-in-depth)
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in GDPR_TABLES:
        # Drop the tenant isolation policy
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

        # Disable RLS (also removes FORCE)
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Drop unique partial index on idempotency_key
    op.drop_index("ix_agent_instances_idempotency", table_name="agent_instances")

    # Drop FK constraints from GDPR tables
    op.drop_constraint("fk_consents_tenant_id", "consents")
    op.drop_constraint("fk_data_subject_requests_tenant_id", "data_subject_requests")
    op.drop_constraint("fk_data_retention_policies_tenant_id", "data_retention_policies")
