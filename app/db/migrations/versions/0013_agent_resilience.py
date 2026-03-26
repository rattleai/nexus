"""Add heartbeat and checkpoint columns to agent_instances for resilience.

Enables three-tier stale instance detection:
  - Tier 1: PENDING stuck (created_at based)
  - Tier 2: RUNNING with stale heartbeat (last_heartbeat_at based)
  - Tier 3: RUNNING without heartbeat (legacy created_at fallback)

Also stores incremental step progress in last_checkpoint so partial
metrics (steps, tokens, cost) survive worker crashes.

Revision ID: 0013_agent_resilience
Revises: 0012_parallel_agent_instances
Create Date: 2026-03-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0013_agent_resilience"
down_revision = "0012_parallel_agent_instances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_instances",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_instances",
        sa.Column("last_checkpoint", JSONB, server_default="{}", nullable=False),
    )
    op.create_index(
        "ix_agent_inst_status_heartbeat",
        "agent_instances",
        ["status", "last_heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_inst_status_heartbeat", table_name="agent_instances")
    op.drop_column("agent_instances", "last_checkpoint")
    op.drop_column("agent_instances", "last_heartbeat_at")
