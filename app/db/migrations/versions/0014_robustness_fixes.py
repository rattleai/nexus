"""Add ON DELETE CASCADE to agent_definition_memory_entries FK.

Without CASCADE, hard-deleting an agent definition raises IntegrityError
because orphaned memory entries reference the deleted definition.

Revision ID: 0014_robustness_fixes
Revises: 0013_agent_resilience
Create Date: 2026-03-24
"""

from alembic import op

revision = "0014_robustness_fixes"
down_revision = "0013_agent_resilience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "agent_definition_memory_entries_definition_id_fkey",
        "agent_definition_memory_entries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "agent_definition_memory_entries_definition_id_fkey",
        "agent_definition_memory_entries",
        "agent_definitions",
        ["definition_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "agent_definition_memory_entries_definition_id_fkey",
        "agent_definition_memory_entries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "agent_definition_memory_entries_definition_id_fkey",
        "agent_definition_memory_entries",
        "agent_definitions",
        ["definition_id"],
        ["id"],
    )
