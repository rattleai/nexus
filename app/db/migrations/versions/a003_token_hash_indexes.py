"""Add indexes on token_hash columns for fast lookups.

These columns are used in auth flows (refresh, verify-email, reset-password,
invitation acceptance) and currently rely on sequential scans.

Revision ID: a003_token_hashes
Revises: a002_perf_indexes
Create Date: 2026-03-05
"""

from alembic import op

revision = "a003_token_hashes"
down_revision = "a002_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Refresh tokens: lookup by token_hash during refresh/logout
    op.create_index(
        "ix_refresh_tokens_token_hash",
        "refresh_tokens",
        ["token_hash"],
        unique=True,
    )

    # Email verification tokens: lookup by token_hash during verify/reset
    op.create_index(
        "ix_email_verification_tokens_token_hash",
        "email_verification_tokens",
        ["token_hash"],
    )

    # Invitations: lookup by token_hash during acceptance
    op.create_index(
        "ix_invitations_token_hash",
        "invitations",
        ["token_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_invitations_token_hash", table_name="invitations")
    op.drop_index("ix_email_verification_tokens_token_hash", table_name="email_verification_tokens")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
