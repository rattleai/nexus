"""Add xai to aiprovider enum for X.AI (Grok) support.

Revision ID: 0012_add_xai_provider
Revises: 0011_gdpr_rls_policies
Create Date: 2026-03-21
"""

from alembic import op

revision = "0012_add_xai_provider"
down_revision = "0011_gdpr_rls_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE aiprovider ADD VALUE IF NOT EXISTS 'xai'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values directly.
    # A full enum recreation would be needed, but is rarely worth the risk.
    # The unused 'xai' value is harmless if this migration is rolled back.
    pass
