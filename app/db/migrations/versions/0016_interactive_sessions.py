"""Add interactive conversation support to agent sessions.

Extends AgentSession with definition_id, turn tracking, aggregate metrics,
and sliding TTL for multi-turn conversations. Adds session_id FK to
AgentInstance for linking turns back to their conversation.

Revision ID: 0016_interactive_sessions
Revises: 0015_merge_heads
Create Date: 2026-03-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_interactive_sessions"
down_revision = "0015_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── AgentSession: add interactive conversation columns ──────────
    op.add_column(
        "agent_sessions",
        sa.Column(
            "definition_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_definitions.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("is_interactive", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("turn_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("total_cost_usd", sa.Numeric(12, 6), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("idle_timeout_seconds", sa.Integer(), server_default="3600", nullable=False),
    )

    # Composite index for listing conversations per agent
    op.create_index(
        "ix_agent_session_definition",
        "agent_sessions",
        ["tenant_id", "definition_id", "status"],
    )

    # ── AgentInstance: add session_id FK ────────────────────────────
    op.add_column(
        "agent_instances",
        sa.Column(
            "session_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_agent_inst_session",
        "agent_instances",
        ["session_id"],
    )

    # ── Backfill: link existing instances to their sessions ────────
    # Best-effort: set agent_instances.session_id from agent_sessions.instance_id
    op.execute(
        """
        UPDATE agent_instances ai
        SET session_id = s.id
        FROM agent_sessions s
        WHERE s.instance_id = ai.id
          AND ai.session_id IS NULL
        """
    )

    # Backfill: set definition_id on existing sessions from their instance
    op.execute(
        """
        UPDATE agent_sessions s
        SET definition_id = ai.definition_id
        FROM agent_instances ai
        WHERE ai.id = s.instance_id
          AND s.definition_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_agent_inst_session", table_name="agent_instances")
    op.drop_column("agent_instances", "session_id")
    op.drop_index("ix_agent_session_definition", table_name="agent_sessions")
    op.drop_column("agent_sessions", "idle_timeout_seconds")
    op.drop_column("agent_sessions", "last_activity_at")
    op.drop_column("agent_sessions", "total_cost_usd")
    op.drop_column("agent_sessions", "total_tokens")
    op.drop_column("agent_sessions", "turn_count")
    op.drop_column("agent_sessions", "is_interactive")
    op.drop_column("agent_sessions", "definition_id")
