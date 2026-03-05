"""Add missing composite indexes for production query performance.

Covers common query patterns: tenant-scoped listings, status filtering,
token lookups, and subscription queries.

Revision ID: a002_perf_indexes
Revises: a001_enterprise
Create Date: 2026-03-05
"""

from alembic import op

revision = "a002_perf_indexes"
down_revision = "a001_enterprise"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Jobs: tenant + created_at for paginated listing (descending)
    op.create_index(
        "ix_jobs_tenant_created",
        "jobs",
        ["tenant_id", "created_at"],
    )

    # Jobs: status + started_at for stale processing cleanup
    op.create_index(
        "ix_jobs_status_started",
        "jobs",
        ["status", "started_at"],
    )

    # API keys: tenant + created_at for listing
    op.create_index(
        "ix_api_keys_tenant_created",
        "api_keys",
        ["tenant_id", "created_at"],
    )

    # Refresh tokens: expiry for cleanup task
    op.create_index(
        "ix_refresh_tokens_expires",
        "refresh_tokens",
        ["expires_at"],
    )

    # Refresh tokens: user + revoked for login validation
    op.create_index(
        "ix_refresh_tokens_user_revoked",
        "refresh_tokens",
        ["user_id", "revoked"],
    )

    # Email verification tokens: expiry for cleanup
    op.create_index(
        "ix_email_verification_tokens_expires",
        "email_verification_tokens",
        ["expires_at"],
    )

    # Subscriptions: status for billing queries
    op.create_index(
        "ix_subscriptions_status",
        "subscriptions",
        ["status"],
    )

    # Webhook deliveries: status + next_retry for retry processing
    op.create_index(
        "ix_webhook_deliveries_next_retry",
        "webhook_deliveries",
        ["next_retry_at"],
    )

    # Notifications: user + tenant + created_at for inbox queries
    op.create_index(
        "ix_notifications_user_tenant_created",
        "notifications",
        ["user_id", "tenant_id", "created_at"],
    )

    # Usage records: tenant + metric + period for quota checks
    # (already exists as ix_usage_records_tenant_metric_period, skip)

    # Invitations: status + expires_at for cleanup task
    op.create_index(
        "ix_invitations_status_expires",
        "invitations",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_invitations_status_expires", table_name="invitations")
    op.drop_index("ix_notifications_user_tenant_created", table_name="notifications")
    op.drop_index("ix_webhook_deliveries_next_retry", table_name="webhook_deliveries")
    op.drop_index("ix_subscriptions_status", table_name="subscriptions")
    op.drop_index("ix_email_verification_tokens_expires", table_name="email_verification_tokens")
    op.drop_index("ix_refresh_tokens_user_revoked", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_expires", table_name="refresh_tokens")
    op.drop_index("ix_api_keys_tenant_created", table_name="api_keys")
    op.drop_index("ix_jobs_status_started", table_name="jobs")
    op.drop_index("ix_jobs_tenant_created", table_name="jobs")
