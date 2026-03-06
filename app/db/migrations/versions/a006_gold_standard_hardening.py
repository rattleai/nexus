"""Gold-standard hardening: RLS on AI tables, wallet CHECK constraint, missing indexes.

Addresses:
1. Row-Level Security on all AI infrastructure tables (tenant_ai_provider_keys,
   token_wallets, wallet_transactions, ai_usage_logs, prompt_templates) — these
   were added in a005 but RLS was never enabled, unlike the original tables in a001.
2. CHECK constraint on token_wallets.balance_tokens >= 0 to prevent negative
   balances at the database level (defense-in-depth beyond optimistic locking).
3. Index on subscriptions.stripe_customer_id — webhook handlers query by this
   column but it was missing an index, causing full table scans.
4. RLS on billing/collaboration/enterprise tables that were also missed in a001.

Revision ID: a006_gold_standard
Revises: a005
Create Date: 2026-03-06
"""

from alembic import op

revision = "a006_gold_standard"
down_revision = "a005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── RLS on AI tables (missed in a005) ────────────────────
    ai_tables = [
        "tenant_ai_provider_keys",
        "token_wallets",
        "wallet_transactions",
        "ai_usage_logs",
        "prompt_templates",
    ]
    for table in ai_tables:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "tenant_isolation_{table}" ON "{table}" '
            f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )

    # ── RLS on billing/collaboration/enterprise tables (missed in a001) ──
    additional_tables = [
        "subscriptions",
        "usage_records",
        "invitations",
        "notifications",
        "webhook_endpoints",
        "webhook_deliveries",
        "sso_configurations",
    ]
    for table in additional_tables:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')

    # Tables with direct tenant_id column
    for table in ["subscriptions", "usage_records", "invitations", "notifications",
                   "webhook_endpoints", "sso_configurations"]:
        op.execute(
            f'CREATE POLICY "tenant_isolation_{table}" ON "{table}" '
            f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )

    # webhook_deliveries: isolate via the parent endpoint's tenant_id
    op.execute(
        'CREATE POLICY "tenant_isolation_webhook_deliveries" ON "webhook_deliveries" '
        "USING (endpoint_id IN ("
        "  SELECT id FROM webhook_endpoints "
        "  WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        "))"
    )

    # ── CHECK constraint: wallet balance must not go negative ──
    op.create_check_constraint(
        "ck_token_wallet_balance_non_negative",
        "token_wallets",
        "balance_tokens >= 0",
    )

    # ── Missing index: subscriptions.stripe_customer_id ──────
    # Stripe webhook handlers (invoice.paid, invoice.payment_failed) query
    # by stripe_customer_id — without this index they do full table scans.
    op.create_index(
        "ix_subscriptions_customer_id",
        "subscriptions",
        ["stripe_customer_id"],
    )

    # ── Partial index: audit_logs for non-null tenant_id ─────
    # Most audit log queries filter by tenant_id. A partial index excluding
    # NULLs is smaller and faster for tenant-scoped queries.
    op.create_index(
        "ix_audit_logs_tenant_occurred_partial",
        "audit_logs",
        ["tenant_id", "occurred_at"],
        postgresql_where="tenant_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_tenant_occurred_partial", table_name="audit_logs")
    op.drop_index("ix_subscriptions_customer_id", table_name="subscriptions")
    op.drop_constraint("ck_token_wallet_balance_non_negative", "token_wallets")

    # Drop RLS on billing/collaboration/enterprise tables
    additional_tables = [
        "webhook_deliveries", "sso_configurations", "webhook_endpoints",
        "notifications", "invitations", "usage_records", "subscriptions",
    ]
    for table in additional_tables:
        op.execute(f'DROP POLICY IF EXISTS "tenant_isolation_{table}" ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')

    # Drop RLS on AI tables
    ai_tables = [
        "prompt_templates", "ai_usage_logs", "wallet_transactions",
        "token_wallets", "tenant_ai_provider_keys",
    ]
    for table in ai_tables:
        op.execute(f'DROP POLICY IF EXISTS "tenant_isolation_{table}" ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
