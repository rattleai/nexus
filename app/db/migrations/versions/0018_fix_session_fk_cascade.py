"""Fix session_id FK to use ON DELETE SET NULL.

The FK created in 0016_interactive_sessions.py defaults to RESTRICT,
which prevents session deletion when instances reference it. SET NULL
preserves instance records for billing/audit while allowing session cleanup.

Revision ID: 0018_fix_session_fk_cascade
Revises: 0017_agent_security_columns
Create Date: 2026-03-28
"""

from alembic import op
from sqlalchemy import text

revision = "0018_fix_session_fk_cascade"
down_revision = "0017_agent_security_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing FK constraint (name may vary — use IF EXISTS for safety)
    op.execute(text(
        "ALTER TABLE agent_instances "
        "DROP CONSTRAINT IF EXISTS agent_instances_session_id_fkey"
    ))
    # Re-add with ON DELETE SET NULL to preserve instances when sessions are deleted
    op.execute(text(
        "ALTER TABLE agent_instances "
        "ADD CONSTRAINT agent_instances_session_id_fkey "
        "FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE SET NULL"
    ))


def downgrade() -> None:
    # Revert to original RESTRICT behavior
    op.execute(text(
        "ALTER TABLE agent_instances "
        "DROP CONSTRAINT IF EXISTS agent_instances_session_id_fkey"
    ))
    op.execute(text(
        "ALTER TABLE agent_instances "
        "ADD CONSTRAINT agent_instances_session_id_fkey "
        "FOREIGN KEY (session_id) REFERENCES agent_sessions(id)"
    ))
