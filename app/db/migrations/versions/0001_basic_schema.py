"""Basic schema — single migration that builds the complete database.

Replaces the prior chain of 37 migrations (0001_consolidated_schema through
0037_hnsw_index_tuning) with one authoritative migration that produces the
exact final schema in a single upgrade(). For fresh installs only — no
compatibility bridge with partially-migrated databases.

Sections:
    1.  Extensions (pgvector, pgvectorscale)
    2.  Enums
    3.  Core multi-tenant tables
    4.  Auth / mobile / webhooks
    5.  GDPR tables
    6.  Agent runtime
    7.  CPQ (product configurator)
    8.  Datasource + RAG scaffolding
    9.  data_source_chunks (partitioned) + per-partition vector indexes
    10. RAG evaluation / A/B / graph / materialized view
    11. Triggers and functions
    12. RLS policies

Revision ID: 0001_basic_schema
Revises: (root)
Create Date: 2026-04-12
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, ENUM as PG_ENUM, JSONB, UUID

revision = "0001_basic_schema"
down_revision = None
branch_labels = None
depends_on = None


# ── Helpers ──────────────────────────────────────────────────────────

TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

NUM_CHUNK_PARTITIONS = 16
HNSW_M = 24
HNSW_EF_CONSTRUCTION = 128


def _create_enum(name: str, values: list[str]) -> None:
    val_list = ", ".join(f"'{v}'" for v in values)
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({val_list}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )


def _rls(table: str, tenant_col: str = "tenant_id") -> None:
    """Enable RLS with tenant isolation (USING + WITH CHECK + FORCE)."""
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" '
        f"USING ({tenant_col} = {TENANT_SETTING}) "
        f"WITH CHECK ({tenant_col} = {TENANT_SETTING})"
    )


def _hnsw_index(name: str, table: str, col: str, ops: str) -> None:
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
        f"USING hnsw ({col} {ops}) "
        f"WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})"
    )


# ── Upgrade ──────────────────────────────────────────────────────────


def upgrade() -> None:
    _create_extensions()
    _create_enums()
    _create_core_tables()
    _create_auth_mobile_webhook_tables()
    _create_gdpr_tables()
    _create_agent_tables()
    _create_cpq_tables()
    _create_datasource_scaffolding()
    _create_partitioned_chunks()
    _create_rag_infrastructure()
    _create_triggers()
    _apply_rls()
    _seed_capability_presets()


# ── 1. Extensions ────────────────────────────────────────────────────


def _create_extensions() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # pgvectorscale is optional — no-op if unavailable on the server
    op.execute(
        "DO $$ BEGIN "
        "CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE; "
        "EXCEPTION WHEN undefined_file THEN NULL; "
        "WHEN OTHERS THEN NULL; END $$;"
    )


# ── 2. Enums ─────────────────────────────────────────────────────────


def _create_enums() -> None:
    _create_enum("userrole", ["owner", "admin", "member", "viewer"])
    _create_enum("jobstatus", ["pending", "processing", "completed", "failed", "cancelled"])
    _create_enum("invitationstatus", ["pending", "accepted", "expired", "revoked"])
    _create_enum("plantier", ["free", "starter", "pro", "enterprise"])
    _create_enum(
        "subscriptionstatus",
        ["active", "past_due", "canceled", "trialing", "incomplete"],
    )
    _create_enum("ssoprovider", ["saml", "oidc"])
    _create_enum(
        "aiprovider",
        ["openai", "anthropic", "google", "mistral", "deepseek", "qwen", "aleph_alpha", "xai"],
    )
    _create_enum(
        "wallettransactiontype",
        ["topup", "consumption", "refund", "adjustment", "bonus"],
    )
    _create_enum("agent_status", ["draft", "active", "disabled"])
    _create_enum(
        "instance_status",
        ["pending", "running", "paused", "completed", "failed", "cancelled"],
    )
    _create_enum("session_status", ["active", "completed", "expired"])
    _create_enum("workflow_status", ["draft", "active", "disabled"])
    _create_enum(
        "workflow_run_status",
        ["pending", "running", "waiting_approval", "completed", "failed", "cancelled"],
    )
    _create_enum("tool_source", ["builtin", "tenant", "marketplace"])
    # CPQ enums (sa.Enum creates these on first use in 0019; create upfront here)
    _create_enum("productstatus", ["draft", "active", "deprecated", "archived"])
    _create_enum("characteristictype", ["enum", "numeric", "boolean", "text"])
    _create_enum(
        "constrainttype",
        ["requires", "excludes", "selection_condition", "default_value", "formula", "table"],
    )
    _create_enum("bomitemtype", ["component", "sub_assembly", "phantom", "reference"])
    _create_enum(
        "configurationstatus",
        ["in_progress", "complete", "invalid", "locked"],
    )
    _create_enum(
        "pricingruletype",
        [
            "base_price",
            "option_surcharge",
            "volume_discount",
            "conditional",
            "formula",
            "tiered",
            "margin",
        ],
    )
    # Datasource + GDPR enums (defined on ORM models, must match them exactly)
    _create_enum("cloudprovider", ["google_drive", "dropbox", "onedrive"])
    _create_enum("datasourcetype", ["upload", "cloud_drive", "url", "paste"])
    _create_enum("datasourcestatus", ["pending", "processing", "ready", "error"])
    _create_enum(
        "consent_type",
        [
            "terms_of_service",
            "privacy_policy",
            "marketing",
            "data_processing",
            "cookies",
            "third_party_sharing",
        ],
    )
    _create_enum(
        "dsar_type",
        ["access", "rectification", "erasure", "portability", "restriction", "objection"],
    )
    _create_enum("dsar_status", ["received", "in_progress", "completed", "rejected"])


# ── 3. Core multi-tenant tables ─────────────────────────────────────


def _create_core_tables() -> None:
    # audit_logs (tenant_id nullable → no RLS; immutability enforced via trigger)
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("actor_id", sa.String(255), nullable=True),
        sa.Column("actor_type", sa.String(50), server_default="user", nullable=False),
        sa.Column("action", sa.String(50), nullable=False, index=True),
        sa.Column("resource_type", sa.String(100), nullable=False, index=True),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("changes", JSONB, nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            index=True,
        ),
    )
    op.create_index("ix_audit_logs_tenant_occurred", "audit_logs", ["tenant_id", "occurred_at"])
    op.create_index("ix_audit_logs_actor_occurred", "audit_logs", ["actor_id", "occurred_at"])

    # feature_flags (global, no RLS)
    op.create_table(
        "feature_flags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("enabled", sa.Boolean, server_default="false", nullable=False),
        sa.Column("rollout_percentage", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # plans (global)
    op.create_table(
        "plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column(
            "tier",
            PG_ENUM("free", "starter", "pro", "enterprise", name="plantier", create_type=False),
            nullable=False,
        ),
        sa.Column("stripe_price_id", sa.String(255), nullable=True, unique=True),
        sa.Column("price_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("billing_period", sa.String(20), server_default=sa.text("'monthly'"), nullable=False),
        sa.Column("limits", JSONB, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("features", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # credit_packs (global)
    op.create_table(
        "credit_packs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("stripe_price_id", sa.String(255), nullable=False, unique=True),
        sa.Column("display_order", sa.Integer, server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
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
        sa.Column("plan", sa.String(50), server_default=sa.text("'free'"), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("settings", JSONB, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # users (locale + mfa_enabled folded in)
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True, index=True),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("email_verified", sa.Boolean, server_default="false", nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("locale", sa.String(10), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_users_email_unique",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(255), server_default=sa.text("'default'"), nullable=False),
        sa.Column("rate_limit", sa.Integer, nullable=True),
        sa.Column("scopes", JSONB, nullable=True),
        sa.Column("active", sa.Boolean, server_default="true", nullable=False),
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
        sa.Column(
            "status",
            PG_ENUM(
                "pending", "processing", "completed", "failed", "cancelled",
                name="jobstatus", create_type=False,
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
            index=True,
        ),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("webhook_url", sa.String(2048), nullable=True),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("sync_version", sa.BigInteger, server_default="0", nullable=False),
        sa.Column("sync_checksum", sa.String(64), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
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
        sa.Column("is_default", sa.Boolean, server_default="false", nullable=False),
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
        sa.Column(
            "provider_type",
            PG_ENUM("saml", "oidc", name="ssoprovider", create_type=False),
            nullable=False,
        ),
        sa.Column("entity_id", sa.String(512), nullable=True),
        sa.Column("metadata_url", sa.String(2048), nullable=True),
        sa.Column("certificate", sa.Text, nullable=True),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("client_secret_encrypted", sa.Text, nullable=True),
        sa.Column("issuer_url", sa.String(2048), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True, unique=True),
        sa.Column("jit_provisioning", sa.Boolean, server_default="true", nullable=False),
        sa.Column("active", sa.Boolean, server_default="true", nullable=False),
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
        sa.Column(
            "status",
            PG_ENUM(
                "active", "past_due", "canceled", "trialing", "incomplete",
                name="subscriptionstatus", create_type=False,
            ),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
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
        sa.Column(
            "provider",
            PG_ENUM(
                "openai", "anthropic", "google", "mistral", "deepseek", "qwen", "aleph_alpha", "xai",
                name="aiprovider", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("encrypted_api_key", sa.Text, nullable=False),
        sa.Column("display_name", sa.String(255), server_default=sa.text("'default'"), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint(
        "uq_tenant_provider_key_name",
        "tenant_ai_provider_keys",
        ["tenant_id", "provider", "display_name"],
    )
    op.create_index(
        "ix_tenant_ai_keys_tenant_provider",
        "tenant_ai_provider_keys",
        ["tenant_id", "provider"],
    )

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
        sa.Column("currency", sa.String(3), server_default=sa.text("'USD'"), nullable=False),
        sa.Column("auto_refill_enabled", sa.Boolean, server_default="false", nullable=False),
        sa.Column("auto_refill_threshold_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("auto_refill_amount_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("stripe_payment_method_id", sa.String(255), nullable=True),
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
        sa.Column("value", sa.Integer, server_default="0", nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_usage_records_tenant_metric_period",
        "usage_records",
        ["tenant_id", "metric", "period_start"],
    )

    # wallet_transactions
    op.create_table(
        "wallet_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column(
            "type",
            PG_ENUM(
                "topup", "consumption", "refund", "adjustment", "bonus",
                name="wallettransactiontype", create_type=False,
            ),
            nullable=False,
        ),
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
        "ix_wallet_tx_tenant_reference_unique",
        "wallet_transactions",
        ["tenant_id", "reference_id"],
        unique=True,
        postgresql_where=sa.text("reference_id IS NOT NULL"),
    )
    op.create_unique_constraint(
        "uq_wallet_transactions_idempotency",
        "wallet_transactions",
        ["tenant_id", "reference_id", "type"],
    )

    # ai_usage_logs
    op.create_table(
        "ai_usage_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 8), server_default="0", nullable=False),
        sa.Column("billed_amount_usd", sa.Numeric(12, 8), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'success'"), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("key_source", sa.String(20), server_default=sa.text("'platform'"), nullable=False),
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
        sa.Column("events", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("active", sa.Boolean, server_default="true", nullable=False),
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
        sa.Column("active", sa.Boolean, server_default="true", nullable=False),
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
    op.create_index(
        "ix_changelog_tenant_entity_version",
        "change_log",
        ["tenant_id", "entity_type", "sync_version"],
    )
    op.create_index("ix_changelog_entity", "change_log", ["entity_type", "entity_id"])

    # processed_events (consumer idempotency)
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_processed_events_processed_at", "processed_events", ["processed_at"])


# ── 4. Auth / mobile / webhook deliveries ───────────────────────────


def _create_auth_mobile_webhook_tables() -> None:
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

    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

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

    op.create_table(
        "tenant_memberships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column(
            "role",
            PG_ENUM("owner", "admin", "member", "viewer", name="userrole", create_type=False),
            server_default=sa.text("'member'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_tenant_user", "tenant_memberships", ["tenant_id", "user_id"])

    op.create_table(
        "invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "role",
            PG_ENUM("owner", "admin", "member", "viewer", name="userrole", create_type=False),
            server_default=sa.text("'member'"),
            nullable=False,
        ),
        sa.Column("invited_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column(
            "status",
            PG_ENUM(
                "pending", "accepted", "expired", "revoked",
                name="invitationstatus", create_type=False,
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_invitations_tenant_email", "invitations", ["tenant_id", "email"])

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
        sa.Column("sync_version", sa.BigInteger, server_default="0", nullable=False),
        sa.Column("sync_checksum", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"])

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

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "endpoint_id",
            UUID(as_uuid=True),
            sa.ForeignKey("webhook_endpoints.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("event", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_webhook_deliveries_endpoint_created",
        "webhook_deliveries",
        ["endpoint_id", "created_at"],
    )


# ── 5. GDPR tables ──────────────────────────────────────────────────


def _create_gdpr_tables() -> None:
    op.create_table(
        "consents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "consent_type",
            PG_ENUM(
                "terms_of_service", "privacy_policy", "marketing", "data_processing",
                "cookies", "third_party_sharing",
                name="consent_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("granted", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_consents_user_type", "consents", ["user_id", "consent_type"])
    op.create_index("ix_consents_tenant", "consents", ["tenant_id"])

    op.create_table(
        "data_subject_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "request_type",
            PG_ENUM(
                "access", "rectification", "erasure", "portability", "restriction", "objection",
                name="dsar_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            PG_ENUM(
                "received", "in_progress", "completed", "rejected",
                name="dsar_status", create_type=False,
            ),
            nullable=False,
            server_default="received",
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("response_notes", sa.Text, nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("processed_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_dsar_tenant_status", "data_subject_requests", ["tenant_id", "status"])
    op.create_index("ix_dsar_user", "data_subject_requests", ["user_id"])

    op.create_table(
        "data_retention_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("retention_days", sa.Integer, nullable=False),
        sa.Column("archive_before_delete", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_retention_tenant_resource",
        "data_retention_policies",
        ["tenant_id", "resource_type"],
        unique=True,
    )


# ── 6. Agent runtime ────────────────────────────────────────────────


def _create_agent_tables() -> None:
    # agent_policies (no FKs to other agent tables — create first)
    op.create_table(
        "agent_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("max_spend_per_run_usd", sa.Float, nullable=True),
        sa.Column("max_spend_per_day_usd", sa.Float, nullable=True),
        sa.Column("max_spend_per_month_usd", sa.Float, nullable=True),
        sa.Column("allowed_tools", JSONB, server_default="[]"),
        sa.Column("denied_tools", JSONB, server_default="[]"),
        sa.Column("require_approval_for", JSONB, server_default="[]"),
        sa.Column("approval_timeout_seconds", sa.Integer, server_default="300"),
        sa.Column("approval_default_action", sa.String(10), server_default="deny"),
        sa.Column("max_requests_per_minute", sa.Integer, nullable=True),
        sa.Column("max_steps_per_run", sa.Integer, nullable=True),
        sa.Column("rules", JSONB, server_default="{}"),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name", name="uq_agent_policy_name"),
    )

    # workflow_definitions
    op.create_table(
        "workflow_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column(
            "status",
            PG_ENUM("draft", "active", "disabled", name="workflow_status", create_type=False),
            server_default="draft",
        ),
        sa.Column("definition", JSONB, nullable=False, server_default="{}"),
        sa.Column("governance", JSONB, server_default="{}"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_workflow_def_tenant_slug"),
    )

    # workflow_runs
    op.create_table(
        "workflow_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_definitions.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            PG_ENUM(
                "pending", "running", "waiting_approval", "completed", "failed", "cancelled",
                name="workflow_run_status", create_type=False,
            ),
            server_default="pending",
        ),
        sa.Column("state", JSONB, server_default="{}"),
        sa.Column("input_data", JSONB, server_default="{}"),
        sa.Column("output_data", JSONB, server_default="{}"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("total_steps", sa.Integer, server_default="0"),
        sa.Column("total_tokens", sa.Integer, server_default="0"),
        sa.Column("total_cost_usd", sa.Float, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_workflow_run_tenant_status", "workflow_runs", ["tenant_id", "status"])
    op.create_index("ix_workflow_run_workflow", "workflow_runs", ["workflow_id"])
    op.create_index(
        "ix_workflow_run_workflow_status",
        "workflow_runs",
        ["workflow_id", "status"],
    )

    # agent_definitions
    op.create_table(
        "agent_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column(
            "status",
            PG_ENUM("draft", "active", "disabled", name="agent_status", create_type=False),
            server_default="draft",
        ),
        sa.Column("system_prompt", sa.Text, server_default=""),
        sa.Column("model", sa.String(100), server_default="gpt-4o"),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column("allowed_tools", JSONB, server_default="[]"),
        sa.Column("max_steps_per_run", sa.Integer, server_default="50"),
        sa.Column("max_duration_seconds", sa.Integer, server_default="300"),
        sa.Column("max_tokens_per_run", sa.Integer, server_default="100000"),
        sa.Column("sandbox_enabled", sa.Boolean, server_default="false"),
        sa.Column("memory_config", JSONB, server_default="{}"),
        sa.Column("governance_policy", JSONB, server_default="{}"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("output_schema", JSONB, nullable=False, server_default="{}"),
        sa.Column("tool_versions", JSONB, nullable=False, server_default="{}"),
        sa.Column("parallel_tool_execution", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("max_concurrent_instances", sa.Integer, nullable=False, server_default="0"),
        sa.Column("db_access_policy", JSONB, nullable=False, server_default="{}"),
        sa.Column("behavioral_baseline", JSONB, nullable=False, server_default="{}"),
        sa.Column("capabilities", JSONB, nullable=False, server_default="[]"),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_agent_def_tenant_slug"),
    )
    op.create_index("ix_agent_def_tenant_status", "agent_definitions", ["tenant_id", "status"])

    # agent_instances — create without session_id FK (circular with agent_sessions),
    # will be added after agent_sessions exists
    op.create_table(
        "agent_instances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "definition_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_definitions.id", ondelete="CASCADE", name="fk_agent_instances_definition_id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            PG_ENUM(
                "pending", "running", "paused", "completed", "failed", "cancelled",
                name="instance_status", create_type=False,
            ),
            server_default="pending",
        ),
        sa.Column("steps_executed", sa.Integer, server_default="0"),
        sa.Column("tokens_used", sa.Integer, server_default="0"),
        sa.Column("cost_usd", sa.Float, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_data", JSONB, server_default="{}"),
        sa.Column("output_data", JSONB, server_default="{}"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checkpoint", JSONB, nullable=False, server_default="{}"),
        sa.Column("capability_token_hash", sa.String(64), nullable=True),
        sa.Column("capability_scope", JSONB, nullable=False, server_default="{}"),
        # session_id added after agent_sessions exists (circular FK)
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "definition_id", "idempotency_key",
            name="uq_agent_instance_idempotency",
        ),
    )
    op.create_index("ix_agent_inst_tenant_status", "agent_instances", ["tenant_id", "status"])
    op.create_index("ix_agent_inst_definition", "agent_instances", ["definition_id"])
    op.create_index("ix_agent_inst_workflow_run", "agent_instances", ["workflow_run_id"])
    op.create_index("ix_agent_inst_status_created", "agent_instances", ["status", "created_at"])
    op.create_index("ix_agent_inst_tenant_def", "agent_instances", ["tenant_id", "definition_id"])
    op.create_index(
        "ix_agent_inst_status_heartbeat",
        "agent_instances",
        ["status", "last_heartbeat_at"],
    )
    op.create_index("ix_agent_inst_session", "agent_instances", ["session_id"])
    op.create_index(
        "ix_agent_instances_idempotency",
        "agent_instances",
        ["tenant_id", "idempotency_key"],
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # agent_sessions
    op.create_table(
        "agent_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "instance_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "definition_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_definitions.id"),
            nullable=True,
        ),
        sa.Column(
            "status",
            PG_ENUM("active", "completed", "expired", name="session_status", create_type=False),
            server_default="active",
        ),
        sa.Column("messages", JSONB, server_default="[]"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_interactive", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("turn_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idle_timeout_seconds", sa.Integer, nullable=False, server_default="3600"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_session_instance", "agent_sessions", ["instance_id"])
    op.create_index(
        "ix_agent_session_expires_at",
        "agent_sessions",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_agent_session_definition",
        "agent_sessions",
        ["tenant_id", "definition_id", "status"],
    )

    # Now close the circular dependency: agent_instances.session_id FK → agent_sessions
    op.create_foreign_key(
        "agent_instances_session_id_fkey",
        "agent_instances",
        "agent_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # agent_memory_entries
    op.create_table(
        "agent_memory_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "instance_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("namespace", sa.String(100), server_default="default"),
        sa.Column("key", sa.String(500), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("embedding", JSONB, nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("instance_id", "namespace", "key", name="uq_agent_memory_instance_ns_key"),
    )
    # vector + halfvec columns
    op.execute(
        "ALTER TABLE agent_memory_entries "
        "ADD COLUMN embedding_vec vector(1536), "
        "ADD COLUMN embedding_halfvec halfvec(1536)"
    )
    op.create_index("ix_agent_memory_tenant", "agent_memory_entries", ["tenant_id"])
    op.create_index("ix_agent_memory_instance_ns", "agent_memory_entries", ["instance_id", "namespace"])
    op.create_index(
        "ix_agent_memory_expires_at",
        "agent_memory_entries",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    _hnsw_index(
        "ix_agent_memory_embedding_vec",
        "agent_memory_entries",
        "embedding_vec",
        "vector_cosine_ops",
    )
    _hnsw_index(
        "ix_agent_memory_embedding_halfvec",
        "agent_memory_entries",
        "embedding_halfvec",
        "halfvec_cosine_ops",
    )
    # DiskANN on agent_memory_entries (conditional on pgvectorscale)
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') THEN "
        "CREATE INDEX IF NOT EXISTS ix_ame_embedding_diskann "
        "ON agent_memory_entries USING diskann (embedding_vec) "
        "WITH (storage_layout = 'memory_optimized'); "
        "END IF; END $$;"
    )

    # agent_definition_memory_entries (shared memory across instances of a definition)
    op.create_table(
        "agent_definition_memory_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "definition_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("namespace", sa.String(100), server_default="shared", nullable=False),
        sa.Column("key", sa.String(500), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("embedding", JSONB, nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("definition_id", "namespace", "key", name="uq_agent_def_memory_def_ns_key"),
    )
    op.create_index(
        "ix_agent_def_memory_tenant",
        "agent_definition_memory_entries",
        ["tenant_id"],
    )
    op.create_index(
        "ix_agent_def_memory_definition_ns",
        "agent_definition_memory_entries",
        ["definition_id", "namespace"],
    )

    # tenant_tools
    op.create_table(
        "tenant_tools",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column(
            "source",
            PG_ENUM("builtin", "tenant", "marketplace", name="tool_source", create_type=False),
            server_default="tenant",
        ),
        sa.Column("input_schema", JSONB, server_default="{}"),
        sa.Column("output_schema", JSONB, server_default="{}"),
        sa.Column("endpoint_url", sa.String(2048), nullable=True),
        sa.Column("auth_config", JSONB, server_default="{}"),
        sa.Column("schema_hash", sa.String(64), nullable=True),
        sa.Column("tool_signature_secret_encrypted", sa.Text, nullable=True),
        sa.Column("trust_level", sa.String(20), nullable=False, server_default="untrusted"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("health_check_url", sa.String(2048), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("version_notes", sa.Text, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "tool_name", name="uq_tenant_tool_name"),
    )

    # capability_presets (shared + tenant-scoped; tenant_id nullable)
    op.create_table(
        "capability_presets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default="", nullable=False),
        sa.Column("icon", sa.String(50), server_default="Shield", nullable=False),
        sa.Column("capabilities", JSONB, nullable=False),
        sa.Column("additional_tools", JSONB, server_default="[]", nullable=False),
        sa.Column("governance_overrides", JSONB, server_default="{}", nullable=False),
        sa.Column("is_system", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_capability_preset_slug"),
    )
    # Partial unique index for system presets (tenant_id IS NULL)
    op.execute(
        "CREATE UNIQUE INDEX uq_capability_preset_system_slug "
        "ON capability_presets (slug) WHERE tenant_id IS NULL"
    )


# ── 7. CPQ tables ───────────────────────────────────────────────────


def _create_cpq_tables() -> None:
    op.create_table(
        "product_families",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_product_family_slug", "product_families", ["tenant_id", "slug"])
    op.create_index("ix_product_families_tenant", "product_families", ["tenant_id"])
    op.create_index("ix_product_families_deleted_at", "product_families", ["deleted_at"])

    op.create_table(
        "products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("product_families.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("sku_prefix", sa.String(50), nullable=True),
        sa.Column(
            "status",
            PG_ENUM(
                "draft", "active", "deprecated", "archived",
                name="productstatus", create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_product_slug", "products", ["tenant_id", "slug"])
    op.create_index("ix_products_tenant_status", "products", ["tenant_id", "status"])
    op.create_index("ix_products_family_id", "products", ["family_id"])
    op.create_index("ix_products_deleted_at", "products", ["deleted_at"])

    op.create_table(
        "product_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="false"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_product_version_number",
        "product_versions",
        ["product_id", "version_number"],
    )
    op.create_index("ix_product_versions_product_active", "product_versions", ["product_id", "is_active"])
    op.create_index("ix_product_versions_tenant_id", "product_versions", ["tenant_id"])

    op.create_table(
        "characteristic_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_char_group_slug", "characteristic_groups", ["tenant_id", "slug"])
    op.create_index("ix_characteristic_groups_tenant_id", "characteristic_groups", ["tenant_id"])
    op.create_index("ix_characteristic_groups_deleted_at", "characteristic_groups", ["deleted_at"])

    op.create_table(
        "characteristics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "group_id",
            UUID(as_uuid=True),
            sa.ForeignKey("characteristic_groups.id"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "char_type",
            PG_ENUM(
                "enum", "numeric", "boolean", "text",
                name="characteristictype", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("numeric_min", sa.Float, nullable=True),
        sa.Column("numeric_max", sa.Float, nullable=True),
        sa.Column("numeric_step", sa.Float, nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("is_required", sa.Boolean, server_default="false"),
        sa.Column("is_multi_select", sa.Boolean, server_default="false"),
        sa.Column("default_value", sa.String(500), nullable=True),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_characteristic_slug", "characteristics", ["tenant_id", "slug"])
    op.create_index("ix_characteristics_tenant_group", "characteristics", ["tenant_id", "group_id"])
    op.create_index("ix_characteristics_deleted_at", "characteristics", ["deleted_at"])

    op.create_table(
        "characteristic_values",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "characteristic_id",
            UUID(as_uuid=True),
            sa.ForeignKey("characteristics.id"),
            nullable=False,
        ),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("label", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("is_default", sa.Boolean, server_default="false"),
        sa.Column("price_adjustment", sa.Numeric(12, 4), nullable=True),
        sa.Column("image_url", sa.String(2048), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_char_value", "characteristic_values", ["characteristic_id", "value"])
    op.create_index("ix_char_values_characteristic", "characteristic_values", ["characteristic_id"])
    op.create_index("ix_characteristic_values_tenant_id", "characteristic_values", ["tenant_id"])

    op.create_table(
        "characteristic_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column(
            "characteristic_id",
            UUID(as_uuid=True),
            sa.ForeignKey("characteristics.id"),
            nullable=False,
        ),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("is_required", sa.Boolean, nullable=True),
        sa.Column("default_value", sa.String(500), nullable=True),
        sa.Column("min_select", sa.Integer, nullable=True),
        sa.Column("max_select", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "min_select IS NULL OR min_select >= 0",
            name="ck_char_assignments_min_select_gte_0",
        ),
        sa.CheckConstraint(
            "max_select IS NULL OR max_select >= 1",
            name="ck_char_assignments_max_select_gte_1",
        ),
        sa.CheckConstraint(
            "min_select IS NULL OR max_select IS NULL OR min_select <= max_select",
            name="ck_char_assignments_min_lte_max",
        ),
    )
    op.create_unique_constraint(
        "uq_product_characteristic",
        "characteristic_assignments",
        ["product_id", "characteristic_id"],
    )
    op.create_index(
        "ix_char_assignments_product",
        "characteristic_assignments",
        ["product_id"],
    )
    op.create_index(
        "ix_characteristic_assignments_tenant_id",
        "characteristic_assignments",
        ["tenant_id"],
    )

    op.create_table(
        "constraint_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_constraint_groups_product", "constraint_groups", ["product_id"])
    op.create_index("ix_constraint_groups_tenant_id", "constraint_groups", ["tenant_id"])
    op.create_index("ix_constraint_groups_deleted_at", "constraint_groups", ["deleted_at"])

    op.create_table(
        "constraint_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("group_id", UUID(as_uuid=True), sa.ForeignKey("constraint_groups.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "constraint_type",
            PG_ENUM(
                "requires", "excludes", "selection_condition", "default_value", "formula", "table",
                name="constrainttype", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("expression", JSONB, nullable=False),
        sa.Column("priority", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_constraint_rules_product", "constraint_rules", ["product_id"])
    op.create_index(
        "ix_constraint_rules_product_type",
        "constraint_rules",
        ["product_id", "constraint_type"],
    )
    op.create_index("ix_constraint_rules_tenant_id", "constraint_rules", ["tenant_id"])
    op.create_index("ix_constraint_rules_deleted_at", "constraint_rules", ["deleted_at"])

    op.create_table(
        "variant_tables",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("columns", JSONB, nullable=False),
        sa.Column("rows", JSONB, nullable=False),
        sa.Column("input_columns", JSONB, nullable=False),
        sa.Column("output_columns", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_variant_tables_product", "variant_tables", ["product_id"])
    op.create_index("ix_variant_tables_tenant_id", "variant_tables", ["tenant_id"])

    op.create_table(
        "product_media",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("media_type", sa.String(50), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("alt_text", sa.String(500), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_media_entity", "product_media", ["entity_type", "entity_id"])
    op.create_index("ix_product_media_tenant", "product_media", ["tenant_id"])

    op.create_table(
        "bom_headers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("bom_type", sa.String(50), server_default="manufacturing"),
        sa.Column("is_primary", sa.Boolean, server_default="false"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bom_headers_product", "bom_headers", ["product_id"])
    op.create_index("ix_bom_headers_tenant_product", "bom_headers", ["tenant_id", "product_id"])
    op.create_index("ix_bom_headers_deleted_at", "bom_headers", ["deleted_at"])

    op.create_table(
        "bom_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("bom_header_id", UUID(as_uuid=True), sa.ForeignKey("bom_headers.id"), nullable=False),
        sa.Column("parent_item_id", UUID(as_uuid=True), sa.ForeignKey("bom_items.id"), nullable=True),
        sa.Column(
            "item_type",
            PG_ENUM(
                "component", "sub_assembly", "phantom", "reference",
                name="bomitemtype", create_type=False,
            ),
            server_default="component",
        ),
        sa.Column("part_number", sa.String(100), nullable=False),
        sa.Column("part_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("quantity", sa.Numeric(12, 4), server_default="1.0000"),
        sa.Column("quantity_expression", JSONB, nullable=True),
        sa.Column("unit_of_measure", sa.String(20), server_default="EA"),
        sa.Column("sub_product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("selection_condition", JSONB, nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("is_optional", sa.Boolean, server_default="false"),
        sa.Column("unit_cost", sa.Numeric(12, 4), nullable=True),
        sa.Column("lead_time_days", sa.Integer, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bom_items_header", "bom_items", ["bom_header_id"])
    op.create_index("ix_bom_items_part_number", "bom_items", ["tenant_id", "part_number"])
    op.create_index("ix_bom_items_parent_item_id", "bom_items", ["parent_item_id"])
    op.create_index("ix_bom_items_sub_product_id", "bom_items", ["sub_product_id"])
    op.create_index("ix_bom_items_deleted_at", "bom_items", ["deleted_at"])

    op.create_table(
        "configuration_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_partial", sa.Boolean, server_default="true"),
        sa.Column("is_public", sa.Boolean, server_default="false"),
        sa.Column("selections", JSONB, nullable=False, server_default="[]"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_config_templates_tenant_product",
        "configuration_templates",
        ["tenant_id", "product_id"],
    )

    op.create_table(
        "configuration_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column(
            "product_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("product_versions.id"),
            nullable=True,
        ),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column(
            "status",
            PG_ENUM(
                "in_progress", "complete", "invalid", "locked",
                name="configurationstatus", create_type=False,
            ),
            server_default="in_progress",
        ),
        sa.Column("is_valid", sa.Boolean, server_default="false"),
        sa.Column("is_complete", sa.Boolean, server_default="false"),
        sa.Column("validation_errors", JSONB, nullable=True),
        sa.Column("available_domains", JSONB, nullable=True),
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("configuration_templates.id"),
            nullable=True,
        ),
        sa.Column("external_reference", sa.String(255), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_config_sessions_tenant_product",
        "configuration_sessions",
        ["tenant_id", "product_id"],
    )
    op.create_index("ix_config_sessions_user", "configuration_sessions", ["user_id"])
    op.create_index("ix_config_sessions_status", "configuration_sessions", ["tenant_id", "status"])

    op.create_table(
        "configuration_selections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("configuration_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "characteristic_id",
            UUID(as_uuid=True),
            sa.ForeignKey("characteristics.id"),
            nullable=False,
        ),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("is_auto_set", sa.Boolean, server_default="false"),
        sa.Column("set_by_rule_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_config_selections_session", "configuration_selections", ["session_id"])
    op.create_index(
        "ix_config_selections_session_char",
        "configuration_selections",
        ["session_id", "characteristic_id"],
    )
    op.create_index(
        "ix_configuration_selections_tenant_id",
        "configuration_selections",
        ["tenant_id"],
    )

    op.create_table(
        "configured_boms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("configuration_sessions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("bom_header_id", UUID(as_uuid=True), sa.ForeignKey("bom_headers.id"), nullable=False),
        sa.Column("resolved_items", JSONB, nullable=False),
        sa.Column("total_components", sa.Integer, server_default="0"),
        sa.Column("total_cost", sa.Numeric(14, 4), nullable=True),
        sa.Column("selection_snapshot", JSONB, nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolution_duration_ms", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_configured_boms_tenant", "configured_boms", ["tenant_id"])
    op.create_index("ix_configured_boms_session", "configured_boms", ["session_id"])

    op.create_table(
        "pricing_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "rule_type",
            PG_ENUM(
                "base_price", "option_surcharge", "volume_discount", "conditional",
                "formula", "tiered", "margin",
                name="pricingruletype", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("expression", JSONB, nullable=False),
        sa.Column("priority", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(3), server_default="EUR"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pricing_rules_product", "pricing_rules", ["product_id"])
    op.create_index(
        "ix_pricing_rules_product_type",
        "pricing_rules",
        ["product_id", "rule_type"],
    )
    op.create_index("ix_pricing_rules_tenant_id", "pricing_rules", ["tenant_id"])
    op.create_index("ix_pricing_rules_deleted_at", "pricing_rules", ["deleted_at"])

    op.create_table(
        "configuration_pricing",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("configuration_sessions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("currency", sa.String(3), server_default="EUR"),
        sa.Column("base_price", sa.Numeric(14, 4), server_default="0"),
        sa.Column("total_adjustments", sa.Numeric(14, 4), server_default="0"),
        sa.Column("final_price", sa.Numeric(14, 4), server_default="0"),
        sa.Column("total_cost", sa.Numeric(14, 4), server_default="0"),
        sa.Column("margin_amount", sa.Numeric(14, 4), server_default="0"),
        sa.Column("margin_percentage", sa.Numeric(8, 4), server_default="0"),
        sa.Column("price_breakdown", JSONB, nullable=False, server_default="[]"),
        sa.Column("is_profitable", sa.Boolean, server_default="false"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_config_pricing_tenant", "configuration_pricing", ["tenant_id"])
    op.create_index("ix_config_pricing_session", "configuration_pricing", ["session_id"])


# ── 8. Datasource scaffolding (cloud_connections, data_sources, provenance) ──


def _create_datasource_scaffolding() -> None:
    op.create_table(
        "cloud_connections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "provider",
            PG_ENUM(
                "google_drive", "dropbox", "onedrive",
                name="cloudprovider", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("account_email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text, nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text, nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", JSONB, server_default="[]"),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_cloud_connections_tenant_provider",
        "cloud_connections",
        ["tenant_id", "provider"],
    )
    op.create_index("ix_cloud_connections_tenant", "cloud_connections", ["tenant_id"])

    op.create_table(
        "data_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "source_type",
            PG_ENUM(
                "upload", "cloud_drive", "url", "paste",
                name="datasourcetype", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            PG_ENUM(
                "pending", "processing", "ready", "error",
                name="datasourcestatus", create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("file_key", sa.String(1024), nullable=True),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column(
            "cloud_provider",
            PG_ENUM(
                "google_drive", "dropbox", "onedrive",
                name="cloudprovider", create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "cloud_connection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("cloud_connections.id"),
            nullable=True,
        ),
        sa.Column("cloud_file_id", sa.String(500), nullable=True),
        sa.Column("extraction_result", JSONB, nullable=True),
        sa.Column("extraction_error", sa.Text, nullable=True),
        sa.Column("chunk_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
    )
    op.create_index("ix_data_sources_tenant_status", "data_sources", ["tenant_id", "status"])
    op.create_index("ix_data_sources_tenant_type", "data_sources", ["tenant_id", "source_type"])
    op.create_index("ix_data_sources_cloud_connection_id", "data_sources", ["cloud_connection_id"])
    op.create_index("ix_data_sources_tenant", "data_sources", ["tenant_id"])

    op.create_table(
        "config_item_provenance",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "data_source_id",
            UUID(as_uuid=True),
            sa.ForeignKey("data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_instance_id", UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Float, server_default="1.0", nullable=False),
        sa.Column("extraction_context", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_config_provenance_tenant_entity",
        "config_item_provenance",
        ["tenant_id", "entity_type", "entity_id"],
    )
    op.create_index(
        "ix_config_provenance_tenant_source",
        "config_item_provenance",
        ["tenant_id", "data_source_id"],
    )


# ── 9. Partitioned data_source_chunks (16 hash partitions) ───────────


def _create_partitioned_chunks() -> None:
    # Create the partitioned parent table directly with the final column set
    # (from 0022+0027+0028+0032+0036). Columns kept broad/nullable where the
    # original migrations added them via ALTER TABLE.
    op.execute(
        f"""
        CREATE TABLE data_source_chunks (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            data_source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding JSONB,
            embedding_model VARCHAR(100),
            section_title VARCHAR(500),
            table_index INTEGER,
            embedding_vec vector(1536),
            embedding_halfvec halfvec(1536),
            content_tsv tsvector,
            tags JSONB NOT NULL DEFAULT '[]',
            content_type VARCHAR(50),
            indexed_at TIMESTAMPTZ DEFAULT now(),
            context_preamble TEXT,
            content_with_context TEXT,
            parent_chunk_id UUID,
            chunk_level VARCHAR(20) DEFAULT 'standard',
            content_hash VARCHAR(64),
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, tenant_id)
        ) PARTITION BY HASH (tenant_id)
        """
    )

    for i in range(NUM_CHUNK_PARTITIONS):
        op.execute(
            f"CREATE TABLE data_source_chunks_p{i:02d} "
            f"PARTITION OF data_source_chunks "
            f"FOR VALUES WITH (MODULUS {NUM_CHUNK_PARTITIONS}, REMAINDER {i})"
        )

    # Parent-level indexes (propagate to partitions)
    op.execute("CREATE INDEX ix_dsc_part_tenant ON data_source_chunks (tenant_id)")
    op.execute(
        "CREATE INDEX ix_dsc_part_tenant_source ON data_source_chunks (tenant_id, data_source_id)"
    )
    op.execute(
        "CREATE INDEX ix_dsc_part_tenant_type ON data_source_chunks (tenant_id, content_type)"
    )
    op.execute(
        "CREATE INDEX ix_dsc_part_tenant_indexed ON data_source_chunks (tenant_id, indexed_at)"
    )
    op.execute(
        "CREATE INDEX ix_dsc_part_content_tsv ON data_source_chunks USING gin (content_tsv)"
    )
    op.execute(
        "CREATE INDEX ix_dsc_parent_chunk ON data_source_chunks (parent_chunk_id) "
        "WHERE parent_chunk_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_dsc_chunk_level ON data_source_chunks (tenant_id, chunk_level)"
    )
    op.execute(
        "CREATE INDEX ix_dsc_deleted_at ON data_source_chunks (deleted_at) "
        "WHERE deleted_at IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_dsc_source_content_hash ON data_source_chunks (data_source_id, content_hash)"
    )

    # Per-partition HNSW indexes (PostgreSQL doesn't allow HNSW on a
    # partitioned parent directly). Final 0037 tuning parameters.
    for i in range(NUM_CHUNK_PARTITIONS):
        part = f"data_source_chunks_p{i:02d}"
        _hnsw_index(f"ix_dsc_p{i:02d}_embedding_vec", part, "embedding_vec", "vector_cosine_ops")
        _hnsw_index(
            f"ix_dsc_p{i:02d}_embedding_halfvec",
            part,
            "embedding_halfvec",
            "halfvec_cosine_ops",
        )


# ── 10. RAG infrastructure: evaluation, A/B, graph, materialized view, config ─


def _create_rag_infrastructure() -> None:
    # tenant_rag_configs
    op.create_table(
        "tenant_rag_configs",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            primary_key=True,
        ),
        sa.Column(
            "embedding_model",
            sa.String(100),
            nullable=False,
            server_default="text-embedding-3-small",
        ),
        sa.Column("embedding_dimensions", sa.Integer, nullable=False, server_default="1536"),
        sa.Column("chunking_strategy", sa.String(50), nullable=False, server_default="fixed_size"),
        sa.Column("chunk_size", sa.Integer, nullable=False, server_default="1000"),
        sa.Column("chunk_overlap", sa.Integer, nullable=False, server_default="200"),
        sa.Column("reranker_provider", sa.String(50), nullable=False, server_default="none"),
        sa.Column("reranker_model", sa.String(100), nullable=True),
        sa.Column("contextual_retrieval_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("parent_child_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("query_routing_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("hyde_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("graph_rag_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenant_rag_configs_tenant", "tenant_rag_configs", ["tenant_id"])

    # rag_evaluation_datasets
    op.create_table(
        "rag_evaluation_datasets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("source_type", sa.String(50), nullable=False, server_default="human_annotation"),
        sa.Column("query_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_eval_datasets_tenant_name",
        "rag_evaluation_datasets",
        ["tenant_id", "name"],
        unique=True,
    )

    # rag_evaluation_queries
    op.create_table(
        "rag_evaluation_queries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("expected_answer", sa.Text, nullable=True),
        sa.Column("relevant_chunk_ids", ARRAY(UUID(as_uuid=True)), nullable=True),
        sa.Column("relevance_grades", JSONB, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_eval_queries_dataset",
        "rag_evaluation_queries",
        ["tenant_id", "dataset_id"],
    )

    # rag_evaluation_runs
    op.create_table(
        "rag_evaluation_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", UUID(as_uuid=True), nullable=False),
        sa.Column("run_type", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("aggregate_metrics", JSONB, nullable=True),
        sa.Column("query_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_eval_runs_tenant_dataset",
        "rag_evaluation_runs",
        ["tenant_id", "dataset_id", "created_at"],
    )

    # rag_evaluation_results
    op.create_table(
        "rag_evaluation_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query_id", UUID(as_uuid=True), nullable=False),
        sa.Column("retrieved_chunk_ids", ARRAY(UUID(as_uuid=True)), nullable=True),
        sa.Column("retrieved_scores", ARRAY(sa.Float), nullable=True),
        sa.Column("precision_at_k", sa.Float, nullable=True),
        sa.Column("recall_at_k", sa.Float, nullable=True),
        sa.Column("mrr", sa.Float, nullable=True),
        sa.Column("ndcg_at_k", sa.Float, nullable=True),
        sa.Column("faithfulness", sa.Float, nullable=True),
        sa.Column("answer_relevancy", sa.Float, nullable=True),
        sa.Column("generated_answer", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_eval_results_run",
        "rag_evaluation_results",
        ["tenant_id", "run_id"],
    )

    # rag_query_logs
    op.create_table(
        "rag_query_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("search_type", sa.String(20), nullable=True),
        sa.Column("result_count", sa.Integer, nullable=True),
        sa.Column("top_score", sa.Float, nullable=True),
        sa.Column("mean_score", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("cache_hit", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("reranked", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("empty_result", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("search_config", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_query_logs_tenant_created",
        "rag_query_logs",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_rag_query_logs_empty",
        "rag_query_logs",
        ["tenant_id", "empty_result"],
    )

    # rag_ab_experiments
    op.create_table(
        "rag_ab_experiments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("control_config", JSONB, nullable=False),
        sa.Column("variant_config", JSONB, nullable=False),
        sa.Column("traffic_split", sa.Float, server_default="0.5"),
        sa.Column("sample_size_target", sa.Integer, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("results", JSONB, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_ab_experiments_tenant_name",
        "rag_ab_experiments",
        ["tenant_id", "name"],
        unique=True,
    )
    op.create_index(
        "ix_rag_ab_experiments_status",
        "rag_ab_experiments",
        ["tenant_id", "status"],
    )

    # rag_ab_assignments
    op.create_table(
        "rag_ab_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query_log_id", UUID(as_uuid=True), nullable=True),
        sa.Column("arm", sa.String(20), nullable=False),
        sa.Column("config_used", JSONB, nullable=False),
        sa.Column("result_count", sa.Integer, nullable=True),
        sa.Column("top_score", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("user_feedback", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_ab_assignments_experiment",
        "rag_ab_assignments",
        ["tenant_id", "experiment_id", "arm", "created_at"],
    )

    # rag_entities + embedding column
    op.create_table(
        "rag_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_entities_tenant_name_type",
        "rag_entities",
        ["tenant_id", "name", "entity_type"],
        unique=True,
    )
    op.execute("ALTER TABLE rag_entities ADD COLUMN embedding_vec vector(1536)")

    # rag_relationships
    op.create_table(
        "rag_relationships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(100), nullable=False),
        sa.Column("weight", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("chunk_id", UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_relationships_source",
        "rag_relationships",
        ["tenant_id", "source_entity_id"],
    )
    op.create_index(
        "ix_rag_relationships_target",
        "rag_relationships",
        ["tenant_id", "target_entity_id"],
    )
    op.create_index("ix_rag_relationships_chunk", "rag_relationships", ["chunk_id"])

    # mv_tenant_chunk_stats — materialized view
    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_tenant_chunk_stats AS
        SELECT tenant_id,
               COUNT(*) AS chunk_count,
               COUNT(*) FILTER (WHERE embedding_vec IS NOT NULL) AS embedded_count,
               COUNT(*) FILTER (WHERE parent_chunk_id IS NOT NULL) AS child_count,
               COUNT(*) FILTER (WHERE context_preamble IS NOT NULL) AS contextualized_count,
               MAX(indexed_at) AS last_indexed_at
        FROM data_source_chunks
        GROUP BY tenant_id
        WITH DATA
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_mv_tenant_chunk_stats_tenant "
        "ON mv_tenant_chunk_stats (tenant_id)"
    )


# ── 11. Triggers and functions ──────────────────────────────────────


def _create_triggers() -> None:
    # audit_logs immutability trigger
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            IF current_setting('app.audit_purge_enabled', true) = 'true' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit_logs table is immutable: % operations are not allowed',
                TG_OP
                USING HINT = 'Set app.audit_purge_enabled=true for compliance-mandated purge';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_immutability_trigger
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
        """
    )

    # data_source_chunks tsvector trigger (partition-aware name from 0031)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION dsc_tsvector_update() RETURNS trigger AS $$
        BEGIN
            NEW.content_tsv := to_tsvector('english', COALESCE(NEW.content, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER dsc_tsvector_trigger
        BEFORE INSERT OR UPDATE OF content ON data_source_chunks
        FOR EACH ROW EXECUTE FUNCTION dsc_tsvector_update()
        """
    )


# ── 12. RLS policies (USING + WITH CHECK + FORCE) ────────────────────


def _apply_rls() -> None:
    # Core multi-tenant tables (0001 + 0007 final form)
    for table in [
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
    ]:
        _rls(table)

    # GDPR tables (0011)
    for table in ["consents", "data_subject_requests", "data_retention_policies"]:
        _rls(table)

    # Agent tables (0002 + 0013 for agent_definition_memory_entries)
    for table in [
        "agent_policies",
        "workflow_definitions",
        "workflow_runs",
        "agent_definitions",
        "agent_instances",
        "agent_sessions",
        "agent_memory_entries",
        "tenant_tools",
        "agent_definition_memory_entries",
    ]:
        _rls(table)

    # CPQ tables (0019 + 0026 final form)
    for table in [
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
    ]:
        _rls(table)

    # Datasource tables (0024)
    for table in [
        "cloud_connections",
        "data_sources",
        "data_source_chunks",
        "config_item_provenance",
    ]:
        _rls(table)

    # RAG infrastructure (0030 + 0033 + 0034 + 0035)
    for table in [
        "tenant_rag_configs",
        "rag_evaluation_datasets",
        "rag_evaluation_queries",
        "rag_evaluation_runs",
        "rag_evaluation_results",
        "rag_query_logs",
        "rag_ab_experiments",
        "rag_ab_assignments",
        "rag_entities",
        "rag_relationships",
    ]:
        _rls(table)


# ── Seed: capability presets (system-scoped) ────────────────────────


SYSTEM_CAPABILITY_PRESETS: list[dict] = [
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "preset:full-product-manager")),
        "name": "Full Product Manager",
        "slug": "full-product-manager",
        "description": (
            "Full read/write/delete access to all product configurator "
            "capabilities plus AI and file tools."
        ),
        "icon": "ShieldCheck",
        "capabilities": [
            "cpq:products:read", "cpq:products:write", "cpq:products:delete",
            "cpq:characteristics:read", "cpq:characteristics:write",
            "cpq:constraints:read", "cpq:constraints:write", "cpq:constraints:delete",
            "cpq:bom:write",
            "cpq:pricing:read", "cpq:pricing:write", "cpq:pricing:delete",
            "cpq:configurator", "cpq:data", "cpq:versioning",
            "platform:ai", "platform:files",
        ],
        "governance_overrides": {
            "require_approval_for_capabilities": [
                "cpq:products:delete",
                "cpq:pricing:delete",
            ],
        },
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "preset:read-only-analyst")),
        "name": "Read-Only Analyst",
        "slug": "read-only-analyst",
        "description": (
            "View-only access to products, characteristics, constraints, and "
            "pricing simulations."
        ),
        "icon": "Eye",
        "capabilities": [
            "cpq:products:read", "cpq:characteristics:read",
            "cpq:constraints:read", "cpq:pricing:read",
            "cpq:configurator",
            "platform:ai",
        ],
        "governance_overrides": {},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "preset:configuration-builder")),
        "name": "Configuration Builder",
        "slug": "configuration-builder",
        "description": (
            "Create and manage product configurators: products, characteristics, "
            "constraints, and versions."
        ),
        "icon": "Wrench",
        "capabilities": [
            "cpq:products:read", "cpq:products:write",
            "cpq:characteristics:read", "cpq:characteristics:write",
            "cpq:constraints:read", "cpq:constraints:write",
            "cpq:configurator", "cpq:data", "cpq:versioning",
            "platform:ai",
        ],
        "governance_overrides": {},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "preset:pricing-specialist")),
        "name": "Pricing Specialist",
        "slug": "pricing-specialist",
        "description": "Manage pricing rules and simulate pricing for product configurations.",
        "icon": "DollarSign",
        "capabilities": [
            "cpq:products:read", "cpq:characteristics:read",
            "cpq:pricing:read", "cpq:pricing:write",
            "cpq:configurator",
            "platform:ai",
        ],
        "governance_overrides": {},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "preset:code-assistant")),
        "name": "Code Assistant",
        "slug": "code-assistant",
        "description": (
            "AI-powered code execution with file access for data processing "
            "and analysis."
        ),
        "icon": "Code",
        "capabilities": ["platform:ai", "platform:files", "platform:code"],
        "governance_overrides": {"max_spend_per_run_usd": 2.0},
    },
]


def _seed_capability_presets() -> None:
    # Raw INSERTs (rather than op.bulk_insert) so the migration renders
    # correctly in both online and offline `--sql` modes — bulk_insert
    # cannot literal-render JSONB payloads.
    for p in SYSTEM_CAPABILITY_PRESETS:
        capabilities = json.dumps(p["capabilities"]).replace("'", "''")
        governance = json.dumps(p["governance_overrides"]).replace("'", "''")
        description = p["description"].replace("'", "''")
        op.execute(
            "INSERT INTO capability_presets "
            "(id, tenant_id, name, slug, description, icon, capabilities, "
            "additional_tools, governance_overrides, is_system) "
            f"VALUES ('{p['id']}', NULL, '{p['name']}', '{p['slug']}', "
            f"'{description}', '{p['icon']}', '{capabilities}'::jsonb, "
            f"'[]'::jsonb, '{governance}'::jsonb, true)"
        )


# ── Downgrade ────────────────────────────────────────────────────────


def downgrade() -> None:
    """No-op: consolidated migration is for fresh installs only."""
    raise NotImplementedError(
        "0001_basic_schema has no downgrade — it is intended for fresh installs. "
        "To reset the database, drop the schema entirely."
    )
