"""Add indexes, FK ON DELETE actions, and idempotency key for agent subsystem.

Revision ID: 0003_agent_indexes
Revises: 0002_agent_infrastructure
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0003_agent_indexes"
down_revision = "0002_agent_infrastructure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Partial indexes for TTL cleanup queries ──
    op.create_index(
        "ix_agent_memory_expires_at",
        "agent_memory_entries",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_agent_session_expires_at",
        "agent_sessions",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )

    # ── Compound indexes for common list queries ──
    op.create_index(
        "ix_agent_inst_status_created",
        "agent_instances",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_workflow_run_workflow_status",
        "workflow_runs",
        ["workflow_id", "status"],
    )

    # ── Idempotency key on agent_instances ──
    op.add_column(
        "agent_instances",
        sa.Column("idempotency_key", sa.String(255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_agent_instance_idempotency",
        "agent_instances",
        ["tenant_id", "definition_id", "idempotency_key"],
    )

    # ── FK ON DELETE actions ──
    # agent_sessions.instance_id → CASCADE
    op.drop_constraint(
        "agent_sessions_instance_id_fkey", "agent_sessions", type_="foreignkey",
    )
    op.create_foreign_key(
        "agent_sessions_instance_id_fkey",
        "agent_sessions",
        "agent_instances",
        ["instance_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # agent_memory_entries.instance_id → CASCADE
    op.drop_constraint(
        "agent_memory_entries_instance_id_fkey", "agent_memory_entries", type_="foreignkey",
    )
    op.create_foreign_key(
        "agent_memory_entries_instance_id_fkey",
        "agent_memory_entries",
        "agent_instances",
        ["instance_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # agent_instances.workflow_run_id → SET NULL
    op.drop_constraint(
        "agent_instances_workflow_run_id_fkey", "agent_instances", type_="foreignkey",
    )
    op.create_foreign_key(
        "agent_instances_workflow_run_id_fkey",
        "agent_instances",
        "workflow_runs",
        ["workflow_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # ── Revert FK actions ──
    op.drop_constraint(
        "agent_instances_workflow_run_id_fkey", "agent_instances", type_="foreignkey",
    )
    op.create_foreign_key(
        "agent_instances_workflow_run_id_fkey",
        "agent_instances",
        "workflow_runs",
        ["workflow_run_id"],
        ["id"],
    )

    op.drop_constraint(
        "agent_memory_entries_instance_id_fkey", "agent_memory_entries", type_="foreignkey",
    )
    op.create_foreign_key(
        "agent_memory_entries_instance_id_fkey",
        "agent_memory_entries",
        "agent_instances",
        ["instance_id"],
        ["id"],
    )

    op.drop_constraint(
        "agent_sessions_instance_id_fkey", "agent_sessions", type_="foreignkey",
    )
    op.create_foreign_key(
        "agent_sessions_instance_id_fkey",
        "agent_sessions",
        "agent_instances",
        ["instance_id"],
        ["id"],
    )

    # ── Remove idempotency key ──
    op.drop_constraint("uq_agent_instance_idempotency", "agent_instances", type_="unique")
    op.drop_column("agent_instances", "idempotency_key")

    # ── Remove indexes ──
    op.drop_index("ix_workflow_run_workflow_status", "workflow_runs")
    op.drop_index("ix_agent_inst_status_created", "agent_instances")
    op.drop_index("ix_agent_session_expires_at", "agent_sessions")
    op.drop_index("ix_agent_memory_expires_at", "agent_memory_entries")
