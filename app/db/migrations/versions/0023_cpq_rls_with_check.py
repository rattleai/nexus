"""Add WITH CHECK + FORCE ROW LEVEL SECURITY to CPQ tables.

Migration 0016's _rls() helper created USING-only policies for 19 product
configurator tables.  This mirrors the fix applied to core tables in 0007:
recreate policies with WITH CHECK and add FORCE ROW LEVEL SECURITY so the
write path is also protected against cross-tenant inserts/updates.

Revision ID: 0023_cpq_rls_with_check
Revises: 0022_capability_model
Create Date: 2026-03-28
"""

from alembic import op

revision = "0023_cpq_rls_with_check"
down_revision = "0022_capability_model"
branch_labels = None
depends_on = None

TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# All 19 CPQ tables from migration 0016 that had USING-only policies
CPQ_RLS_TABLES = [
    "product_families",
    "products",
    "product_versions",
    "characteristic_groups",
    "characteristics",
    "characteristic_values",
    "characteristic_assignments",
    "constraint_groups",
    "constraint_rules",
    "variant_tables",
    "product_media",
    "bom_headers",
    "bom_items",
    "configuration_templates",
    "configuration_sessions",
    "configuration_selections",
    "configured_boms",
    "pricing_rules",
    "configuration_pricing",
]


def upgrade() -> None:
    for table in CPQ_RLS_TABLES:
        # Drop existing USING-only policy (idempotent)
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')

        # Recreate with both USING and WITH CHECK
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            f"USING (tenant_id = {TENANT_SETTING}) "
            f"WITH CHECK (tenant_id = {TENANT_SETTING})"
        )

        # Force RLS even for table owners (defense-in-depth)
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in CPQ_RLS_TABLES:
        # Restore original USING-only policies
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            f"USING (tenant_id = {TENANT_SETTING})"
        )
        # Remove FORCE (revert to default NO FORCE)
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
