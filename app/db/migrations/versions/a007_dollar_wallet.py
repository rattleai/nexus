"""Replace token wallets with USD dollar wallets; add credit packs table.

- Drop token_wallets table (greenfield — no data to migrate)
- Create dollar_wallets table with USD balance, auto-refill settings
- Update wallet_transactions: amount_tokens → amount_usd, balance_after → balance_after_usd,
  add provider_cost_usd, stripe_payment_intent_id
- Update ai_usage_logs: remove billed_tokens, add billed_amount_usd
- Create credit_packs table for Stripe credit pack purchases
- Enable RLS on new tables

Revision ID: a007_dollar_wallet
Revises: a006_gold_standard, c3d4e5f6a7b8
Create Date: 2026-03-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a007_dollar_wallet"
down_revision = ("a006_gold_standard", "c3d4e5f6a7b8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Drop old token_wallets table ──────────────────────────
    # Remove RLS policy first
    op.execute('DROP POLICY IF EXISTS "tenant_isolation_token_wallets" ON "token_wallets"')
    op.execute('ALTER TABLE "token_wallets" DISABLE ROW LEVEL SECURITY')
    op.drop_constraint("ck_token_wallet_balance_non_negative", "token_wallets")
    op.drop_table("token_wallets")

    # ── Create dollar_wallets table ───────────────────────────
    op.create_table(
        "dollar_wallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("balance_usd", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("lifetime_deposited_usd", sa.Numeric(14, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("lifetime_consumed_usd", sa.Numeric(14, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("auto_refill_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("auto_refill_threshold_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("auto_refill_amount_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("stripe_payment_method_id", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("balance_usd >= 0", name="ck_dollar_wallet_balance_non_negative"),
    )

    # RLS on dollar_wallets
    op.execute('ALTER TABLE "dollar_wallets" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "dollar_wallets" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "tenant_isolation_dollar_wallets" ON "dollar_wallets" '
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )

    # ── Update wallet_transactions columns ────────────────────
    # Rename token-based columns to USD-based
    op.alter_column("wallet_transactions", "amount_tokens", new_column_name="amount_usd",
                     type_=sa.Numeric(12, 6), existing_type=sa.Integer)
    op.alter_column("wallet_transactions", "balance_after", new_column_name="balance_after_usd",
                     type_=sa.Numeric(12, 6), existing_type=sa.Integer)

    # Add new columns
    op.add_column("wallet_transactions",
                  sa.Column("provider_cost_usd", sa.Numeric(12, 8), nullable=True))
    op.add_column("wallet_transactions",
                  sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True))

    # ── Update ai_usage_logs ──────────────────────────────────
    # Remove billed_tokens, add billed_amount_usd
    op.drop_column("ai_usage_logs", "billed_tokens")
    op.add_column("ai_usage_logs",
                  sa.Column("billed_amount_usd", sa.Numeric(12, 8), nullable=False, server_default=sa.text("0")))

    # ── Create credit_packs table ─────────────────────────────
    op.create_table(
        "credit_packs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("stripe_price_id", sa.String(255), nullable=False, unique=True),
        sa.Column("display_order", sa.Integer, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    # ── Drop credit_packs ─────────────────────────────────────
    op.drop_table("credit_packs")

    # ── Reverse ai_usage_logs changes ─────────────────────────
    op.drop_column("ai_usage_logs", "billed_amount_usd")
    op.add_column("ai_usage_logs",
                  sa.Column("billed_tokens", sa.Integer, nullable=False, server_default=sa.text("0")))

    # ── Reverse wallet_transactions changes ───────────────────
    op.drop_column("wallet_transactions", "stripe_payment_intent_id")
    op.drop_column("wallet_transactions", "provider_cost_usd")
    op.alter_column("wallet_transactions", "balance_after_usd", new_column_name="balance_after",
                     type_=sa.Integer, existing_type=sa.Numeric(12, 6))
    op.alter_column("wallet_transactions", "amount_usd", new_column_name="amount_tokens",
                     type_=sa.Integer, existing_type=sa.Numeric(12, 6))

    # ── Drop dollar_wallets, recreate token_wallets ───────────
    op.execute('DROP POLICY IF EXISTS "tenant_isolation_dollar_wallets" ON "dollar_wallets"')
    op.execute('ALTER TABLE "dollar_wallets" DISABLE ROW LEVEL SECURITY')
    op.drop_table("dollar_wallets")

    op.create_table(
        "token_wallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("balance_tokens", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("lifetime_deposited", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("lifetime_consumed", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("balance_tokens >= 0", name="ck_token_wallet_balance_non_negative"),
    )

    # Re-enable RLS on token_wallets
    op.execute('ALTER TABLE "token_wallets" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "token_wallets" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "tenant_isolation_token_wallets" ON "token_wallets" '
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
