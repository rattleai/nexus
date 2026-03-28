"""Add heartbeat and checkpoint columns to agent_instances for resilience.

Enables three-tier stale instance detection:
  - Tier 1: PENDING stuck (created_at based)
  - Tier 2: RUNNING with stale heartbeat (last_heartbeat_at based)
  - Tier 3: RUNNING without heartbeat (legacy created_at fallback)

Also stores incremental step progress in last_checkpoint so partial
metrics (steps, tokens, cost) survive worker crashes.

Revision ID: 0014_agent_resilience
Revises: 0013_parallel_agent_instances
Create Date: 2026-03-20
"""

from alembic import op
from sqlalchemy import text

revision = "0014_agent_resilience"
down_revision = "0013_parallel_agent_instances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text(
        "ALTER TABLE agent_instances "
        "ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMP WITH TIME ZONE"
    ))
    op.execute(text(
        "ALTER TABLE agent_instances "
        "ADD COLUMN IF NOT EXISTS last_checkpoint JSONB NOT NULL DEFAULT '{}'"
    ))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_agent_inst_status_heartbeat "
        "ON agent_instances (status, last_heartbeat_at)"
    ))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS ix_agent_inst_status_heartbeat"))
    op.execute(text("ALTER TABLE agent_instances DROP COLUMN IF EXISTS last_checkpoint"))
    op.execute(text("ALTER TABLE agent_instances DROP COLUMN IF EXISTS last_heartbeat_at"))
