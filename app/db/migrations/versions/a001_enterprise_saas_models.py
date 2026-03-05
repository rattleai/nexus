"""Enterprise SaaS models: audit logs, feature flags, invitations, notifications,
webhooks, billing, SSO, email verification, and Row-Level Security policies.

Revision ID: a001_enterprise
Revises: dd9b1b77e51e
Create Date: 2026-03-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision = "a001_enterprise"
down_revision = "dd9b1b77e51e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Audit Logs (immutable, append-only) ──────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
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

    # ── Feature Flags ────────────────────────────────────────
    op.create_table(
        "feature_flags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("enabled", sa.Boolean, server_default="false"),
        sa.Column("rollout_percentage", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "tenant_feature_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("flag_id", UUID(as_uuid=True), sa.ForeignKey("feature_flags.id"), nullable=False, index=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "flag_id", name="uq_tenant_flag"),
    )

    # ── Invitations ──────────────────────────────────────────
    op.create_table(
        "invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("owner", "admin", "member", "viewer", name="userrole", create_type=False), nullable=False),
        sa.Column("invited_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "accepted", "expired", "revoked", name="invitationstatus"),
            server_default="pending",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_invitations_tenant_email", "invitations", ["tenant_id", "email"])

    # ── Notifications ────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"])

    # ── Webhook Endpoints ────────────────────────────────────
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("secret", sa.String(255), nullable=False),
        sa.Column("events", JSONB, server_default="[]"),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
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

    # ── Plans ────────────────────────────────────────────────
    op.create_table(
        "plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column("tier", sa.Enum("free", "starter", "pro", "enterprise", name="plantier"), nullable=False),
        sa.Column("stripe_price_id", sa.String(255), nullable=True, unique=True),
        sa.Column("price_cents", sa.Integer, server_default="0"),
        sa.Column("billing_period", sa.String(20), server_default="'monthly'"),
        sa.Column("limits", JSONB, server_default="{}"),
        sa.Column("features", JSONB, server_default="[]"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── Subscriptions ────────────────────────────────────────
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True, unique=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "past_due", "canceled", "trialing", "incomplete", name="subscriptionstatus"),
            server_default="'active'",
        ),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── Usage Records ────────────────────────────────────────
    op.create_table(
        "usage_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("metric", sa.String(50), nullable=False),
        sa.Column("value", sa.Integer, server_default="0"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_usage_records_tenant_metric_period", "usage_records", ["tenant_id", "metric", "period_start"])

    # ── SSO Configuration ────────────────────────────────────
    op.create_table(
        "sso_configurations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("provider_type", sa.Enum("saml", "oidc", name="ssoprovider"), nullable=False),
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

    # ── Email Verification Tokens ────────────────────────────
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("token_type", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── Row-Level Security Policies ──────────────────────────
    # Enable RLS on tenant-scoped tables as defense-in-depth
    tenant_tables = ["jobs", "api_keys", "users", "tenant_memberships"]
    for table in tenant_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )

    # Seed default plans
    op.execute("""
        INSERT INTO plans (id, name, tier, price_cents, billing_period, limits, features) VALUES
        (gen_random_uuid(), 'Free', 'free', 0, 'monthly',
         '{"api_calls": 1000, "jobs_month": 100, "storage_bytes": 104857600, "users": 3, "api_keys": 2}',
         '["basic_jobs", "file_storage"]'),
        (gen_random_uuid(), 'Starter', 'starter', 2900, 'monthly',
         '{"api_calls": 10000, "jobs_month": 1000, "storage_bytes": 1073741824, "users": 10, "api_keys": 10}',
         '["basic_jobs", "file_storage", "webhooks", "team_management"]'),
        (gen_random_uuid(), 'Pro', 'pro', 9900, 'monthly',
         '{"api_calls": 100000, "jobs_month": 10000, "storage_bytes": 10737418240, "users": 50, "api_keys": 50}',
         '["basic_jobs", "file_storage", "webhooks", "team_management", "sso", "audit_logs", "priority_support"]'),
        (gen_random_uuid(), 'Enterprise', 'enterprise', 0, 'custom',
         '{"api_calls": -1, "jobs_month": -1, "storage_bytes": -1, "users": -1, "api_keys": -1}',
         '["basic_jobs", "file_storage", "webhooks", "team_management", "sso", "audit_logs", "priority_support", "custom_integrations", "sla"]')
    """)


def downgrade() -> None:
    # Drop RLS policies
    tenant_tables = ["jobs", "api_keys", "users", "tenant_memberships"]
    for table in tenant_tables:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Drop tables in reverse dependency order
    op.drop_table("email_verification_tokens")
    op.drop_table("sso_configurations")
    op.drop_table("usage_records")
    op.drop_table("subscriptions")
    op.drop_table("plans")
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
    op.drop_table("notifications")
    op.drop_table("invitations")
    op.drop_table("tenant_feature_overrides")
    op.drop_table("feature_flags")
    op.drop_table("audit_logs")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS invitationstatus")
    op.execute("DROP TYPE IF EXISTS plantier")
    op.execute("DROP TYPE IF EXISTS subscriptionstatus")
    op.execute("DROP TYPE IF EXISTS ssoprovider")
