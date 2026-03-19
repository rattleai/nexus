"""Add parallel_tool_execution flag to agent_definitions.

Allows agents to opt in/out of parallel tool call execution.
Defaults to True (enabled) for new agents.

Revision ID: 0009_parallel_tool_execution
Revises: 0008_audit_log_immutability
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_parallel_tool_execution"
down_revision = "0008_audit_log_immutability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_definitions "
        "ADD COLUMN IF NOT EXISTS parallel_tool_execution BOOLEAN NOT NULL DEFAULT true"
    )


def downgrade() -> None:
    op.drop_column("agent_definitions", "parallel_tool_execution")
