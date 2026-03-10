"""Consolidated schema — single idempotent migration for all tables.

Replaces the broken chain of 9 migrations (bc1f795e..a010) with one
authoritative migration that matches the current ORM models exactly.

Revision ID: 0001_consolidated_schema
Revises: (root)
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001_consolidated_schema"
down_revision = None
branch_labels = None
depends_on = None

# ── Helpers ──────────────────────────────────────────────────────────

TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _create_enum(name: str, values: list[str]) -> None:
    """Create a PG enum type, ignoring if it already exists."""
    val_list = ", ".join(f"'{v}'" for v in values)
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({val_list}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )


def _rls(table: str, tenant_col: str = "tenant_id") -> None:
    """Enable RLS and add a tenant-isolation policy."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({tenant_col} = {TENANT_SETTING})"
    )


# ── Upgrade ──────────────────────────────────────────────────────────


def upgrade() -> None:
    # ── Enum types ───────────────────────────────────────────────────
    _create_enum("userrole", ["owner", "admin", "member", "viewer"])
    _create_enum("jobstatus", ["pending", "processing", "completed", "failed", "cancelled"])
    _create_enum("invitationstatus", ["pending", "accepted", "expired", "revoked"])
    _create_enum("plantier", ["free", "starter", "pro", "enterprise"])
    _create_enum("subscriptionstatus", ["active", "past_due", "canceled", "trialing", "incomplete"])
    _create_enum("ssoprovider", ["saml", "oidc"])
    _create_enum("aiprovider", ["openai", "anthropic", "google", "mistral", "deepseek", "qwen", "aleph_alpha"])
    _create_enum("wallettransactiontype", ["topup", "consumption", "refund", "adjustment", "bonus"])

    # ── No-dependency tables ─────────────────────────────────────────

    # audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("actor_id", sa.String(255), nullable=True),
        sa.Column("actor_type", sa.String(50), server_default="user"),
        sa.Column("action", sa.String(50), nullable=False, index=True),
        sa.Column("resource_type", sa.String(100), nullable=False, index=True),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("changes", JSONB, nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, index=True),
    )
    op.create_index("ix_audit_logs_tenant_occurred", "audit_logs", ["tenant_id", "occurred_at"])
    op.create_index("ix_audit_logs_actor_occurred", "audit_logs", ["actor_id", "occurred_at"])

    # feature_flags
    op.create_table(
        "feature_flags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("enabled", sa.Boolean, server_default="false"),
        sa.Column("rollout_percentage", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # plans
    op.create_table(
        "plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column("tier", sa.Enum("free", "starter", "pro", "enterprise", name="plantier", create_type=False), nullable=False),
        sa.Column("stripe_price_id", sa.String(255), nullable=True, unique=True),
        sa.Column("price_cents", sa.Integer, server_default="0"),
        sa.Column("billing_period", sa.String(20), server_default="'monthly'"),
        sa.Column("limits", JSONB, server_default="'{}'"),
        sa.Column("features", JSONB, server_default="'[]'"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # credit_packs
    op.create_table(
        "credit_packs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("stripe_price_id", sa.String(255), nullable=False, unique=True),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # tenants
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(63), unique=True, nullable=False),
        sa.Column("plan", sa.String(50), server_default="'free'"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("settings", JSONB, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── Depends on tenants ───────────────────────────────────────────

    # users
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True, index=True),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("email_verified", sa.Boolean, server_default="false"),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_users_email_unique", "users", ["email"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(255), server_default="'default'"),
        sa.Column("rate_limit", sa.Integer, nullable=True),
        sa.Column("scopes", JSONB, nullable=True),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_api_keys_hash_active", "api_keys", ["key_hash", "active"])

    # jobs
    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("status", sa.Enum("pending", "processing", "completed", "failed", "cancelled", name="jobstatus", create_type=False), server_default="'pending'", index=True),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("webhook_url", sa.String(2048), nullable=True),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("result", JSONB, nullable=True),
        # SyncMixin
        sa.Column("sync_version", sa.BigInteger, server_default="0", nullable=False),
        sa.Column("sync_checksum", sa.String(64), nullable=True),
        # SoftDeleteMixin
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        # VersionMixin
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        # TimestampMixin
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_jobs_tenant_status", "jobs", ["tenant_id", "status"])

    # prompt_templates
    op.create_table(
        "prompt_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("variables", JSONB, nullable=True),
        sa.Column("is_default", sa.Boolean, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_tenant_prompt_name", "prompt_templates", ["tenant_id", "name"])

    # sso_configurations
    op.create_table(
        "sso_configurations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("provider_type", sa.Enum("saml", "oidc", name="ssoprovider", create_type=False), nullable=False),
        sa.Column("entity_id", sa.String(512), nullable=True),
        sa.Column("metadata_url", sa.String(2048), nullable=True),
        sa.Column("certificate", sa.Text, nullable=True),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("client_secret_encrypted", sa.Text, nullable=True),
        sa.Column("issuer_url", sa.String(2048), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True, unique=True),
        sa.Column("jit_provisioning", sa.Boolean, server_default="true"),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True, unique=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True, index=True),
        sa.Column("status", sa.Enum("active", "past_due", "canceled", "trialing", "incomplete", name="subscriptionstatus", create_type=False), server_default="'active'"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_subscriptions_customer_id", "subscriptions", ["stripe_customer_id"])

    # tenant_ai_provider_keys
    op.create_table(
        "tenant_ai_provider_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("provider", sa.Enum("openai", "anthropic", "google", "mistral", "deepseek", "qwen", "aleph_alpha", name="aiprovider", create_type=False), nullable=False),
        sa.Column("encrypted_api_key", sa.Text, nullable=False),
        sa.Column("display_name", sa.String(255), server_default="'default'"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_tenant_provider_key_name", "tenant_ai_provider_keys", ["tenant_id", "provider", "display_name"])
    op.create_index("ix_tenant_ai_keys_tenant_provider", "tenant_ai_provider_keys", ["tenant_id", "provider"])

    # tenant_feature_overrides
    op.create_table(
        "tenant_feature_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("flag_id", UUID(as_uuid=True), sa.ForeignKey("feature_flags.id"), nullable=False, index=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_tenant_flag", "tenant_feature_overrides", ["tenant_id", "flag_id"])

    # dollar_wallets
    op.create_table(
        "dollar_wallets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("balance_usd", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column("lifetime_deposited_usd", sa.Numeric(14, 6), server_default="0", nullable=False),
        sa.Column("lifetime_consumed_usd", sa.Numeric(14, 6), server_default="0", nullable=False),
        sa.Column("currency", sa.String(3), server_default="'USD'", nullable=False),
        sa.Column("auto_refill_enabled", sa.Boolean, server_default="false"),
        sa.Column("auto_refill_threshold_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("auto_refill_amount_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("stripe_payment_method_id", sa.String(255), nullable=True),
        # VersionMixin
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("balance_usd >= 0", name="ck_dollar_wallet_balance_non_negative"),
    )

    # usage_records
    op.create_table(
        "usage_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("metric", sa.String(50), nullable=False),
        sa.Column("value", sa.Integer, server_default="0"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_usage_records_tenant_metric_period", "usage_records", ["tenant_id", "metric", "period_start"])

    # wallet_transactions
    op.create_table(
        "wallet_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("type", sa.Enum("topup", "consumption", "refund", "adjustment", "bonus", name="wallettransactiontype", create_type=False), nullable=False),
        sa.Column("amount_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("balance_after_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("provider_cost_usd", sa.Numeric(12, 8), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("reference_id", sa.String(255), nullable=True),
        sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_wallet_tx_tenant_created", "wallet_transactions", ["tenant_id", "created_at"])
    op.create_index(
        "ix_wallet_tx_tenant_reference_unique", "wallet_transactions",
        ["tenant_id", "reference_id"],
        unique=True, postgresql_where=sa.text("reference_id IS NOT NULL"),
    )

    # ai_usage_logs
    op.create_table(
        "ai_usage_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, server_default="0"),
        sa.Column("completion_tokens", sa.Integer, server_default="0"),
        sa.Column("total_tokens", sa.Integer, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 8), server_default="0"),
        sa.Column("billed_amount_usd", sa.Numeric(12, 8), server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("status", sa.String(20), server_default="'success'"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("key_source", sa.String(20), server_default="'platform'"),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_ai_usage_tenant_created", "ai_usage_logs", ["tenant_id", "created_at"])
    op.create_index("ix_ai_usage_tenant_model", "ai_usage_logs", ["tenant_id", "model"])

    # webhook_endpoints
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("secret", sa.String(255), nullable=False),
        sa.Column("events", JSONB, server_default="'[]'"),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # oauth_clients
    op.create_table(
        "oauth_clients",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("client_id", sa.String(64), unique=True, nullable=False),
        sa.Column("client_secret_hash", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("scopes", JSONB, nullable=True),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # change_log
    op.create_table(
        "change_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("changed_fields", JSONB, nullable=True),
        sa.Column("sync_version", sa.BigInteger, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_changelog_tenant_entity_version", "change_log", ["tenant_id", "entity_type", "sync_version"])
    op.create_index("ix_changelog_entity", "change_log", ["entity_type", "entity_id"])

    # ── Depends on users ─────────────────────────────────────────────

    # oauth_accounts
    op.create_table(
        "oauth_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("access_token", sa.Text, nullable=True),
        sa.Column("refresh_token", sa.Text, nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_oauth_provider_user", "oauth_accounts", ["provider", "provider_user_id"])

    # refresh_tokens
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # email_verification_tokens
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("token_type", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # tenant_memberships
    op.create_table(
        "tenant_memberships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("role", sa.Enum("owner", "admin", "member", "viewer", name="userrole", create_type=False), server_default="'member'", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_tenant_user", "tenant_memberships", ["tenant_id", "user_id"])

    # invitations
    op.create_table(
        "invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("owner", "admin", "member", "viewer", name="userrole", create_type=False), server_default="'member'", nullable=False),
        sa.Column("invited_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("status", sa.Enum("pending", "accepted", "expired", "revoked", name="invitationstatus", create_type=False), server_default="'pending'"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_invitations_tenant_email", "invitations", ["tenant_id", "email"])

    # notifications
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data", JSONB, nullable=True),
        # SyncMixin
        sa.Column("sync_version", sa.BigInteger, server_default="0", nullable=False),
        sa.Column("sync_checksum", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"])

    # push_subscriptions
    op.create_table(
        "push_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("platform", sa.String(10), nullable=False),
        sa.Column("subscription_data", JSONB, nullable=False),
        sa.Column("device_name", sa.String(255), nullable=True),
        sa.Column("active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_push_subscriptions_user", "push_subscriptions", ["user_id", "active"])
    op.create_index("ix_push_subscriptions_tenant", "push_subscriptions", ["tenant_id"])

    # webauthn_credentials
    op.create_table(
        "webauthn_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("credential_id", sa.String(512), nullable=False, unique=True),
        sa.Column("public_key", sa.Text, nullable=False),
        sa.Column("sign_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("device_name", sa.String(255), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_webauthn_user", "webauthn_credentials", ["user_id"])
    op.create_index("ix_webauthn_credential_id", "webauthn_credentials", ["credential_id"], unique=True)

    # ── Depends on webhook_endpoints ─────────────────────────────────

    # webhook_deliveries
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("endpoint_id", UUID(as_uuid=True), sa.ForeignKey("webhook_endpoints.id"), nullable=False, index=True),
        sa.Column("event", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_webhook_deliveries_endpoint_created", "webhook_deliveries", ["endpoint_id", "created_at"])

    # ── RLS policies ─────────────────────────────────────────────────

    _rls("api_keys")
    _rls("jobs")
    _rls("prompt_templates")
    _rls("sso_configurations")
    _rls("subscriptions")
    _rls("tenant_ai_provider_keys")
    _rls("tenant_feature_overrides")
    _rls("dollar_wallets")
    _rls("usage_records")
    _rls("wallet_transactions")
    _rls("ai_usage_logs")
    _rls("webhook_endpoints")
    _rls("oauth_clients")
    _rls("change_log")
    _rls("invitations")
    _rls("notifications")
    _rls("push_subscriptions")


# ── Downgrade ────────────────────────────────────────────────────────


def downgrade() -> None:
    # Drop tables in reverse dependency order
    tables = [
        "webhook_deliveries",
        "webauthn_credentials",
        "push_subscriptions",
        "notifications",
        "invitations",
        "tenant_memberships",
        "email_verification_tokens",
        "refresh_tokens",
        "oauth_accounts",
        "change_log",
        "oauth_clients",
        "webhook_endpoints",
        "ai_usage_logs",
        "wallet_transactions",
        "usage_records",
        "dollar_wallets",
        "tenant_feature_overrides",
        "tenant_ai_provider_keys",
        "subscriptions",
        "sso_configurations",
        "prompt_templates",
        "jobs",
        "api_keys",
        "users",
        "tenants",
        "credit_packs",
        "plans",
        "feature_flags",
        "audit_logs",
    ]
    for table in tables:
        # Drop RLS policies before dropping the table
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    # Drop enum types
    for enum_name in [
        "wallettransactiontype",
        "aiprovider",
        "ssoprovider",
        "subscriptionstatus",
        "plantier",
        "invitationstatus",
        "jobstatus",
        "userrole",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
