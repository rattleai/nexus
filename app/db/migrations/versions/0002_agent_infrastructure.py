"""Agent execution layer — models for agents, workflows, memory, tools, policies.

Revision ID: 0002_agent_infrastructure
Revises: 0001_consolidated_schema
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002_agent_infrastructure"
down_revision = "0001_consolidated_schema"
branch_labels = None
depends_on = None

TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _create_enum(name: str, values: list[str]) -> None:
    val_list = ", ".join(f"'{v}'" for v in values)
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({val_list}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING (tenant_id = {TENANT_SETTING}) "
        f"WITH CHECK (tenant_id = {TENANT_SETTING});"
    )


def upgrade() -> None:
    # ── Enums ──
    _create_enum("agent_status", ["draft", "active", "disabled"])
    _create_enum("instance_status", ["pending", "running", "paused", "completed", "failed", "cancelled"])
    _create_enum("session_status", ["active", "completed", "expired"])
    _create_enum("workflow_status", ["draft", "active", "disabled"])
    _create_enum("workflow_run_status", ["pending", "running", "waiting_approval", "completed", "failed", "cancelled"])
    _create_enum("tool_source", ["builtin", "tenant", "marketplace"])

    # ── agent_policies (must exist before agent_definitions references it) ──
    op.create_table(
        "agent_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("max_spend_per_run_usd", sa.Float, nullable=True),
        sa.Column("max_spend_per_day_usd", sa.Float, nullable=True),
        sa.Column("max_spend_per_month_usd", sa.Float, nullable=True),
        sa.Column("allowed_tools", JSONB, server_default="[]"),
        sa.Column("denied_tools", JSONB, server_default="[]"),
        sa.Column("require_approval_for", JSONB, server_default="[]"),
        sa.Column("approval_timeout_seconds", sa.Integer, server_default="300"),
        sa.Column("approval_default_action", sa.String(10), server_default="deny"),
        sa.Column("max_requests_per_minute", sa.Integer, nullable=True),
        sa.Column("max_steps_per_run", sa.Integer, nullable=True),
        sa.Column("rules", JSONB, server_default="{}"),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name", name="uq_agent_policy_name"),
    )
    _enable_rls("agent_policies")

    # ── workflow_definitions ──
    op.create_table(
        "workflow_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("status", sa.Enum("draft", "active", "disabled", name="workflow_status", create_type=False), server_default="draft"),
        sa.Column("definition", JSONB, nullable=False, server_default="{}"),
        sa.Column("governance", JSONB, server_default="{}"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_workflow_def_tenant_slug"),
    )
    _enable_rls("workflow_definitions")

    # ── workflow_runs ──
    op.create_table(
        "workflow_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("workflow_id", UUID(as_uuid=True), sa.ForeignKey("workflow_definitions.id"), nullable=False),
        sa.Column("status", sa.Enum("pending", "running", "waiting_approval", "completed", "failed", "cancelled", name="workflow_run_status", create_type=False), server_default="pending"),
        sa.Column("state", JSONB, server_default="{}"),
        sa.Column("input_data", JSONB, server_default="{}"),
        sa.Column("output_data", JSONB, server_default="{}"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("total_steps", sa.Integer, server_default="0"),
        sa.Column("total_tokens", sa.Integer, server_default="0"),
        sa.Column("total_cost_usd", sa.Float, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_workflow_run_tenant_status", "workflow_runs", ["tenant_id", "status"])
    op.create_index("ix_workflow_run_workflow", "workflow_runs", ["workflow_id"])
    _enable_rls("workflow_runs")

    # ── agent_definitions ──
    op.create_table(
        "agent_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("status", sa.Enum("draft", "active", "disabled", name="agent_status", create_type=False), server_default="draft"),
        sa.Column("system_prompt", sa.Text, server_default=""),
        sa.Column("model", sa.String(100), server_default="gpt-4o"),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column("allowed_tools", JSONB, server_default="[]"),
        sa.Column("max_steps_per_run", sa.Integer, server_default="50"),
        sa.Column("max_duration_seconds", sa.Integer, server_default="300"),
        sa.Column("max_tokens_per_run", sa.Integer, server_default="100000"),
        sa.Column("sandbox_enabled", sa.Boolean, server_default="false"),
        sa.Column("memory_config", JSONB, server_default="{}"),
        sa.Column("governance_policy", JSONB, server_default="{}"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_agent_def_tenant_slug"),
    )
    op.create_index("ix_agent_def_tenant_status", "agent_definitions", ["tenant_id", "status"])
    _enable_rls("agent_definitions")

    # ── agent_instances ──
    op.create_table(
        "agent_instances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("definition_id", UUID(as_uuid=True), sa.ForeignKey("agent_definitions.id"), nullable=False),
        sa.Column("status", sa.Enum("pending", "running", "paused", "completed", "failed", "cancelled", name="instance_status", create_type=False), server_default="pending"),
        sa.Column("steps_executed", sa.Integer, server_default="0"),
        sa.Column("tokens_used", sa.Integer, server_default="0"),
        sa.Column("cost_usd", sa.Float, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_data", JSONB, server_default="{}"),
        sa.Column("output_data", JSONB, server_default="{}"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("workflow_run_id", UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_inst_tenant_status", "agent_instances", ["tenant_id", "status"])
    op.create_index("ix_agent_inst_definition", "agent_instances", ["definition_id"])
    op.create_index("ix_agent_inst_workflow_run", "agent_instances", ["workflow_run_id"])
    _enable_rls("agent_instances")

    # ── agent_sessions ──
    op.create_table(
        "agent_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("instance_id", UUID(as_uuid=True), sa.ForeignKey("agent_instances.id"), nullable=False),
        sa.Column("status", sa.Enum("active", "completed", "expired", name="session_status", create_type=False), server_default="active"),
        sa.Column("messages", JSONB, server_default="[]"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_session_instance", "agent_sessions", ["instance_id"])
    _enable_rls("agent_sessions")

    # ── agent_memory_entries ──
    op.create_table(
        "agent_memory_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("instance_id", UUID(as_uuid=True), sa.ForeignKey("agent_instances.id"), nullable=False),
        sa.Column("namespace", sa.String(100), server_default="default"),
        sa.Column("key", sa.String(500), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("embedding", JSONB, nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("instance_id", "namespace", "key", name="uq_agent_memory_instance_ns_key"),
    )
    op.create_index("ix_agent_memory_tenant", "agent_memory_entries", ["tenant_id"])
    op.create_index("ix_agent_memory_instance_ns", "agent_memory_entries", ["instance_id", "namespace"])
    _enable_rls("agent_memory_entries")

    # ── tenant_tools ──
    op.create_table(
        "tenant_tools",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("source", sa.Enum("builtin", "tenant", "marketplace", name="tool_source", create_type=False), server_default="tenant"),
        sa.Column("input_schema", JSONB, server_default="{}"),
        sa.Column("output_schema", JSONB, server_default="{}"),
        sa.Column("endpoint_url", sa.String(2048), nullable=True),
        sa.Column("auth_config", JSONB, server_default="{}"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("health_check_url", sa.String(2048), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "tool_name", name="uq_tenant_tool_name"),
    )
    _enable_rls("tenant_tools")


def downgrade() -> None:
    op.drop_table("tenant_tools")
    op.drop_table("agent_memory_entries")
    op.drop_table("agent_sessions")
    op.drop_table("agent_instances")
    op.drop_table("agent_definitions")
    op.drop_table("workflow_runs")
    op.drop_table("workflow_definitions")
    op.drop_table("agent_policies")

    for enum_name in [
        "tool_source", "workflow_run_status", "workflow_status",
        "session_status", "instance_status", "agent_status",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
