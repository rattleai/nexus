"""Add mobile-first models: push subscriptions, WebAuthn credentials, change log

Revision ID: a2b3c4d5e6f7
Revises: bc1f795e8631
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a2b3c4d5e6f7"
down_revision = "bc1f795e8631"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Push notification subscriptions
    op.create_table(
        "push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("platform", sa.String(10), nullable=False),
        sa.Column("subscription_data", postgresql.JSONB, nullable=False),
        sa.Column("device_name", sa.String(255), nullable=True),
        sa.Column("active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_push_subscriptions_user", "push_subscriptions", ["user_id", "active"])
    op.create_index("ix_push_subscriptions_tenant", "push_subscriptions", ["tenant_id"])

    # WebAuthn credentials
    op.create_table(
        "webauthn_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("credential_id", sa.String(512), nullable=False, unique=True),
        sa.Column("public_key", sa.Text, nullable=False),
        sa.Column("sign_count", sa.Integer, default=0, nullable=False),
        sa.Column("device_name", sa.String(255), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_webauthn_user", "webauthn_credentials", ["user_id"])
    op.create_index("ix_webauthn_credential_id", "webauthn_credentials", ["credential_id"], unique=True)

    # Change log for offline sync
    op.create_table(
        "change_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB, nullable=True),
        sa.Column("sync_version", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_changelog_tenant_entity_version", "change_log", ["tenant_id", "entity_type", "sync_version"])
    op.create_index("ix_changelog_entity", "change_log", ["entity_type", "entity_id"])

    # Add sync columns to jobs table (primary syncable entity)
    op.add_column("jobs", sa.Column("sync_version", sa.BigInteger, nullable=False, server_default=sa.text("0")))
    op.add_column("jobs", sa.Column("sync_checksum", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "sync_checksum")
    op.drop_column("jobs", "sync_version")
    op.drop_table("change_log")
    op.drop_table("webauthn_credentials")
    op.drop_table("push_subscriptions")
