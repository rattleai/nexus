"""Production hardening: FK cascades, idempotency constraints, dedup table.

Revision ID: 0004_production_hardening
Revises: 0003_agent_indexes
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0004_production_hardening"
down_revision = "0003_agent_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── FK cascade: agent_instances.definition_id → agent_definitions.id ──
    # Drop existing FK (auto-generated name) and recreate with ON DELETE CASCADE
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT con.conname "
        "FROM pg_constraint con "
        "JOIN pg_attribute att ON att.attnum = ANY(con.conkey) AND att.attrelid = con.conrelid "
        "WHERE con.conrelid = 'agent_instances'::regclass "
        "AND con.contype = 'f' "
        "AND att.attname = 'definition_id' "
        "LIMIT 1"
    ))
    row = result.fetchone()
    if row:
        op.drop_constraint(row[0], "agent_instances", type_="foreignkey")
    op.create_foreign_key(
        "fk_agent_instances_definition_id",
        "agent_instances",
        "agent_definitions",
        ["definition_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── Unique constraint for idempotent topups ──
    # Prevents duplicate wallet transactions with the same reference_id
    op.create_unique_constraint(
        "uq_wallet_transactions_idempotency",
        "wallet_transactions",
        ["tenant_id", "reference_id", "type"],
    )

    # ── Index for fast idempotency key dedup on agent instances ──
    # (may already exist from 0003, create only if missing)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_agent_instances_idempotency
        ON agent_instances (tenant_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    # ── Table: processed_events for consumer idempotency ──
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

    # Index for cleanup of old processed events
    op.create_index(
        "ix_processed_events_processed_at",
        "processed_events",
        ["processed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_processed_events_processed_at", table_name="processed_events")
    op.drop_table("processed_events")

    op.execute("DROP INDEX IF EXISTS ix_agent_instances_idempotency")

    op.drop_constraint(
        "uq_wallet_transactions_idempotency",
        "wallet_transactions",
        type_="unique",
    )

    # Restore FK without CASCADE
    op.drop_constraint(
        "fk_agent_instances_definition_id",
        "agent_instances",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_agent_instances_definition_id",
        "agent_instances",
        "agent_definitions",
        ["definition_id"],
        ["id"],
    )
