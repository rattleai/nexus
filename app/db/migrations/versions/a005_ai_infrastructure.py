"""AI infrastructure: provider keys, token wallet, usage logs, prompt templates.

Revision ID: a005
Revises: a004_composite_indexes
Create Date: 2026-03-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a005"
down_revision = "a004_composite_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── AIProvider enum type ──────────────────────────────
    ai_provider_enum = postgresql.ENUM(
        "openai", "anthropic", "google", "mistral", "deepseek", "qwen", "aleph_alpha",
        name="aiprovider",
        create_type=False,
    )
    ai_provider_enum.create(op.get_bind(), checkfirst=True)

    # ── WalletTransactionType enum type ───────────────────
    wallet_tx_type_enum = postgresql.ENUM(
        "topup", "consumption", "refund", "adjustment", "bonus",
        name="wallettransactiontype",
        create_type=False,
    )
    wallet_tx_type_enum.create(op.get_bind(), checkfirst=True)

    # ── tenant_ai_provider_keys ───────────────────────────
    op.create_table(
        "tenant_ai_provider_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.Enum("openai", "anthropic", "google", "mistral", "deepseek", "qwen", "aleph_alpha", name="aiprovider", create_type=False), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(255), server_default="default"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenant_ai_keys_tenant_id", "tenant_ai_provider_keys", ["tenant_id"])
    op.create_index("ix_tenant_ai_keys_tenant_provider", "tenant_ai_provider_keys", ["tenant_id", "provider"])
    op.create_unique_constraint(
        "uq_tenant_provider_key_name",
        "tenant_ai_provider_keys",
        ["tenant_id", "provider", "display_name"],
    )

    # ── token_wallets ─────────────────────────────────────
    op.create_table(
        "token_wallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("balance_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("lifetime_purchased", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("lifetime_consumed", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── wallet_transactions ───────────────────────────────
    op.create_table(
        "wallet_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("type", sa.Enum("topup", "consumption", "refund", "adjustment", "bonus", name="wallettransactiontype", create_type=False), nullable=False),
        sa.Column("amount_tokens", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("reference_id", sa.String(255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_wallet_tx_tenant_id", "wallet_transactions", ["tenant_id"])
    op.create_index("ix_wallet_tx_tenant_created", "wallet_transactions", ["tenant_id", "created_at"])

    # ── ai_usage_logs ─────────────────────────────────────
    op.create_table(
        "ai_usage_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), server_default="0"),
        sa.Column("total_tokens", sa.Integer(), server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 8), server_default="0"),
        sa.Column("billed_tokens", sa.Integer(), server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), server_default="success"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("key_source", sa.String(20), server_default="platform"),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_usage_tenant_id", "ai_usage_logs", ["tenant_id"])
    op.create_index("ix_ai_usage_tenant_created", "ai_usage_logs", ["tenant_id", "created_at"])
    op.create_index("ix_ai_usage_tenant_model", "ai_usage_logs", ["tenant_id", "model"])

    # ── prompt_templates ──────────────────────────────────
    op.create_table(
        "prompt_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("variables", postgresql.JSONB(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_prompt_templates_tenant_id", "prompt_templates", ["tenant_id"])
    op.create_unique_constraint("uq_tenant_prompt_name", "prompt_templates", ["tenant_id", "name"])


def downgrade() -> None:
    op.drop_table("prompt_templates")
    op.drop_table("ai_usage_logs")
    op.drop_table("wallet_transactions")
    op.drop_table("token_wallets")
    op.drop_table("tenant_ai_provider_keys")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS wallettransactiontype")
    op.execute("DROP TYPE IF EXISTS aiprovider")
