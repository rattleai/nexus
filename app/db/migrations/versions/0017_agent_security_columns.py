"""Add security columns: db_access_policy, behavioral_baseline, capability tokens.

Adds columns required by the agent security & data protection layer:
  - agent_definitions.db_access_policy — controls DB table access per agent
  - agent_definitions.behavioral_baseline — auto-populated threat detection baseline
  - agent_instances.capability_token_hash — hashed capability token for privilege system
  - agent_instances.capability_scope — JSON scope for capability-based access control

All columns are idempotent (ADD COLUMN IF NOT EXISTS).

Revision ID: 0017_agent_security_columns
Revises: 0016_interactive_sessions
Create Date: 2026-03-27
"""

from alembic import op
from sqlalchemy import text

revision = "0017_agent_security_columns"
down_revision = "0016_interactive_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── agent_definitions: security & governance columns ───────────
    op.execute(text(
        "ALTER TABLE agent_definitions "
        "ADD COLUMN IF NOT EXISTS db_access_policy JSONB NOT NULL DEFAULT '{}'"
    ))
    op.execute(text(
        "ALTER TABLE agent_definitions "
        "ADD COLUMN IF NOT EXISTS behavioral_baseline JSONB NOT NULL DEFAULT '{}'"
    ))

    # ── agent_instances: capability-based privilege columns ────────
    op.execute(text(
        "ALTER TABLE agent_instances "
        "ADD COLUMN IF NOT EXISTS capability_token_hash VARCHAR(64)"
    ))
    op.execute(text(
        "ALTER TABLE agent_instances "
        "ADD COLUMN IF NOT EXISTS capability_scope JSONB NOT NULL DEFAULT '{}'"
    ))


def downgrade() -> None:
    op.execute(text("ALTER TABLE agent_instances DROP COLUMN IF EXISTS capability_scope"))
    op.execute(text("ALTER TABLE agent_instances DROP COLUMN IF EXISTS capability_token_hash"))
    op.execute(text("ALTER TABLE agent_definitions DROP COLUMN IF EXISTS behavioral_baseline"))
    op.execute(text("ALTER TABLE agent_definitions DROP COLUMN IF EXISTS db_access_policy"))
