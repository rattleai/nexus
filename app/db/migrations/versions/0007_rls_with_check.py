"""Add WITH CHECK to RLS policies and FORCE ROW LEVEL SECURITY on core tables.

Migration 0001's _rls() helper created USING-only policies for 17 core tables.
Migration 0002 correctly used USING + WITH CHECK + FORCE for agent tables.
This migration fixes the asymmetry by recreating policies with WITH CHECK
and adding FORCE ROW LEVEL SECURITY to prevent bypasses.

Revision ID: 0007_rls_with_check
Revises: 0006_pgvector_and_gdpr
Create Date: 2026-03-19
"""

from alembic import op

revision = "0007_rls_with_check"
down_revision = "0006_pgvector_and_gdpr"
branch_labels = None
depends_on = None

TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# All 17 core tables from migration 0001 that had USING-only policies
CORE_RLS_TABLES = [
    "api_keys",
    "jobs",
    "prompt_templates",
    "sso_configurations",
    "subscriptions",
    "tenant_ai_provider_keys",
    "tenant_feature_overrides",
    "dollar_wallets",
    "usage_records",
    "wallet_transactions",
    "ai_usage_logs",
    "webhook_endpoints",
    "oauth_clients",
    "change_log",
    "invitations",
    "notifications",
    "push_subscriptions",
]


def upgrade() -> None:
    for table in CORE_RLS_TABLES:
        # Drop existing USING-only policy (idempotent)
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

        # Recreate with both USING and WITH CHECK
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = {TENANT_SETTING}) "
            f"WITH CHECK (tenant_id = {TENANT_SETTING})"
        )

        # Force RLS even for table owners (defense-in-depth)
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in CORE_RLS_TABLES:
        # Restore original USING-only policies
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = {TENANT_SETTING})"
        )
        # Remove FORCE (revert to default NO FORCE)
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
