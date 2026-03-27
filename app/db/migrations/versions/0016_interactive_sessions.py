"""Add interactive conversation support to agent sessions.

Extends AgentSession with definition_id, turn tracking, aggregate metrics,
and sliding TTL for multi-turn conversations. Adds session_id FK to
AgentInstance for linking turns back to their conversation.

Revision ID: 0016_interactive_sessions
Revises: 0015_merge_heads
Create Date: 2026-03-27
"""

from alembic import op
from sqlalchemy import text

revision = "0016_interactive_sessions"
down_revision = "0015_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── AgentSession: add interactive conversation columns ──────────
    op.execute(text(
        "ALTER TABLE agent_sessions "
        "ADD COLUMN IF NOT EXISTS definition_id UUID REFERENCES agent_definitions(id)"
    ))
    op.execute(text(
        "ALTER TABLE agent_sessions "
        "ADD COLUMN IF NOT EXISTS is_interactive BOOLEAN NOT NULL DEFAULT false"
    ))
    op.execute(text(
        "ALTER TABLE agent_sessions "
        "ADD COLUMN IF NOT EXISTS turn_count INTEGER NOT NULL DEFAULT 0"
    ))
    op.execute(text(
        "ALTER TABLE agent_sessions "
        "ADD COLUMN IF NOT EXISTS total_tokens INTEGER NOT NULL DEFAULT 0"
    ))
    op.execute(text(
        "ALTER TABLE agent_sessions "
        "ADD COLUMN IF NOT EXISTS total_cost_usd NUMERIC(12, 6) NOT NULL DEFAULT 0"
    ))
    op.execute(text(
        "ALTER TABLE agent_sessions "
        "ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP WITH TIME ZONE"
    ))
    op.execute(text(
        "ALTER TABLE agent_sessions "
        "ADD COLUMN IF NOT EXISTS idle_timeout_seconds INTEGER NOT NULL DEFAULT 3600"
    ))

    # Composite index for listing conversations per agent
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_agent_session_definition "
        "ON agent_sessions (tenant_id, definition_id, status)"
    ))

    # ── AgentInstance: add session_id FK ────────────────────────────
    op.execute(text(
        "ALTER TABLE agent_instances "
        "ADD COLUMN IF NOT EXISTS session_id UUID REFERENCES agent_sessions(id)"
    ))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_agent_inst_session "
        "ON agent_instances (session_id)"
    ))

    # ── Backfill: link existing instances to their sessions ────────
    # Best-effort: set agent_instances.session_id from agent_sessions.instance_id
    op.execute(text(
        """
        UPDATE agent_instances ai
        SET session_id = s.id
        FROM agent_sessions s
        WHERE s.instance_id = ai.id
          AND ai.session_id IS NULL
        """
    ))

    # Backfill: set definition_id on existing sessions from their instance
    op.execute(text(
        """
        UPDATE agent_sessions s
        SET definition_id = ai.definition_id
        FROM agent_instances ai
        WHERE ai.id = s.instance_id
          AND s.definition_id IS NULL
        """
    ))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS ix_agent_inst_session"))
    op.execute(text("ALTER TABLE agent_instances DROP COLUMN IF EXISTS session_id"))
    op.execute(text("DROP INDEX IF EXISTS ix_agent_session_definition"))
    op.execute(text("ALTER TABLE agent_sessions DROP COLUMN IF EXISTS idle_timeout_seconds"))
    op.execute(text("ALTER TABLE agent_sessions DROP COLUMN IF EXISTS last_activity_at"))
    op.execute(text("ALTER TABLE agent_sessions DROP COLUMN IF EXISTS total_cost_usd"))
    op.execute(text("ALTER TABLE agent_sessions DROP COLUMN IF EXISTS total_tokens"))
    op.execute(text("ALTER TABLE agent_sessions DROP COLUMN IF EXISTS turn_count"))
    op.execute(text("ALTER TABLE agent_sessions DROP COLUMN IF EXISTS is_interactive"))
    op.execute(text("ALTER TABLE agent_sessions DROP COLUMN IF EXISTS definition_id"))
