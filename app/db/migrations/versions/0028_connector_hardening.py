"""Connector hardening: per-tenant OAuth app credentials, OAuth state persistence,
api_config split, trust_level, per-user unique constraint, MCP primitives cache,
durable task handles, discovery cache, broker selection.

This migration implements Phase 0 (security merge blockers) and Phase 1 (MCP
2025-11-25 primitives + RFC 9728/7591 discovery + broker routing) schema
changes for the connector system on top of 0027_connector_system.

Tables created:
    connector_app_credentials  — per-tenant OAuth app (client_id/secret) storage
    connector_oauth_states     — durable OAuth state tokens (survive Redis restart)
    connector_tasks            — async MCP task handles (2025-11-25 Tasks primitive)

Columns added to connector_definitions:
    api_config          JSONB  — HTTP API base + tool routing (separate from auth)
    discovery_cache     JSONB  — cached RFC 9728/8414 discovery result
    discovery_refreshed_at      — TTL for discovery cache
    trust_level         STRING — verified | trusted | untrusted
    broker              STRING — composio | in_house
    requires_app_creds  BOOL   — whether a per-tenant OAuth app must be configured
    registration_endpoint STRING — RFC 7591 DCR endpoint discovered or declared

Columns added to tenant_connections:
    mcp_prompts_cache   JSONB  — cached MCP prompts list
    mcp_capabilities    JSONB  — server capabilities reported at initialize()

Unique constraint replaced on tenant_connections to include connected_by_user_id
so per-user connections are first-class.

Revision ID: 0028_connector_hardening
Revises: 0027_connector_system
Create Date: 2026-04-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0028_connector_hardening"
down_revision = "0027_connector_system"
branch_labels = None
depends_on = None

TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" '
        f"USING (tenant_id = {TENANT_SETTING}) "
        f"WITH CHECK (tenant_id = {TENANT_SETTING})"
    )
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def _drop_rls(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


def upgrade() -> None:
    # ── 1. Per-tenant OAuth app credentials (P0.1) ────────────────────
    # Each tenant provides its own OAuth app (client_id + client_secret) for
    # a given connector slug. This replaces the insecure pattern of storing
    # client_secret in the global connector_definitions.auth_config JSONB.

    op.create_table(
        "connector_app_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connector_slug", sa.String(100), nullable=False),
        sa.Column("client_id_enc", sa.Text(), nullable=True),
        sa.Column("client_secret_enc", sa.Text(), nullable=True),
        sa.Column("webhook_secret_enc", sa.Text(), nullable=True),
        sa.Column("redirect_uri_override", sa.String(2048), nullable=True),
        sa.Column("extra_config", JSONB, nullable=True),
        sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "connector_slug",
            name="uq_connector_app_credentials_tenant_slug",
        ),
    )
    op.create_index(
        "ix_connector_app_credentials_tenant",
        "connector_app_credentials",
        ["tenant_id"],
    )
    _rls("connector_app_credentials")

    # ── 2. Durable OAuth state store (P0.5) ───────────────────────────
    # OAuth state tokens survive Redis restart by being persisted in Postgres.
    # Redis remains as a fast read-through cache.

    op.create_table(
        "connector_oauth_states",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("state_token", sa.String(128), nullable=False),
        sa.Column("connector_slug", sa.String(100), nullable=False),
        sa.Column("payload_enc", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("state_token", name="uq_connector_oauth_state_token"),
    )
    op.create_index(
        "ix_connector_oauth_states_tenant",
        "connector_oauth_states",
        ["tenant_id"],
    )
    op.create_index(
        "ix_connector_oauth_states_expires",
        "connector_oauth_states",
        ["expires_at"],
    )
    _rls("connector_oauth_states")

    # ── 3. Async MCP task handles (P1.1) ──────────────────────────────
    # Persisted handles for MCP 2025-11-25 Tasks primitive. When a tool call
    # returns a task handle instead of an immediate result, a row is created
    # here and the agent can poll via get_task_status.

    op.create_table(
        "connector_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connection_id", UUID(as_uuid=True), sa.ForeignKey("tenant_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mcp_task_id", sa.String(255), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("arguments", JSONB, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="working"),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("input_required", JSONB, nullable=True),
        sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("agent_instance_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_connector_tasks_tenant_status",
        "connector_tasks",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_connector_tasks_connection",
        "connector_tasks",
        ["connection_id"],
    )
    _rls("connector_tasks")

    # ── 4. Extend connector_definitions with P0.6/P0.9/P1.2/P2.4 fields ──

    op.add_column(
        "connector_definitions",
        sa.Column("api_config", JSONB, nullable=True),
    )
    op.add_column(
        "connector_definitions",
        sa.Column("discovery_cache", JSONB, nullable=True),
    )
    op.add_column(
        "connector_definitions",
        sa.Column("discovery_refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "connector_definitions",
        sa.Column("trust_level", sa.String(20), nullable=False, server_default="untrusted"),
    )
    op.add_column(
        "connector_definitions",
        sa.Column("broker", sa.String(20), nullable=False, server_default="in_house"),
    )
    op.add_column(
        "connector_definitions",
        sa.Column("requires_app_credentials", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "connector_definitions",
        sa.Column("registration_endpoint", sa.String(2048), nullable=True),
    )

    # ── 5. Extend tenant_connections with MCP caches ─────────────────

    op.add_column(
        "tenant_connections",
        sa.Column("mcp_prompts_cache", JSONB, nullable=True),
    )
    op.add_column(
        "tenant_connections",
        sa.Column("mcp_capabilities", JSONB, nullable=True),
    )

    # ── 6. Replace unique constraint to include connected_by_user_id (P0.2) ─
    # The existing uq_tenant_connection_account is replaced so multiple users
    # within a tenant can each have their own connection to the same connector
    # with the same account_identifier (e.g., different OAuth scopes).

    op.drop_constraint(
        "uq_tenant_connection_account",
        "tenant_connections",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_tenant_connection_user_account",
        "tenant_connections",
        ["tenant_id", "connector_definition_id", "connected_by_user_id", "account_identifier"],
    )


def downgrade() -> None:
    # Restore the original unique constraint
    op.drop_constraint(
        "uq_tenant_connection_user_account",
        "tenant_connections",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_tenant_connection_account",
        "tenant_connections",
        ["tenant_id", "connector_definition_id", "account_identifier"],
    )

    # Drop extended columns
    op.drop_column("tenant_connections", "mcp_capabilities")
    op.drop_column("tenant_connections", "mcp_prompts_cache")

    op.drop_column("connector_definitions", "registration_endpoint")
    op.drop_column("connector_definitions", "requires_app_credentials")
    op.drop_column("connector_definitions", "broker")
    op.drop_column("connector_definitions", "trust_level")
    op.drop_column("connector_definitions", "discovery_refreshed_at")
    op.drop_column("connector_definitions", "discovery_cache")
    op.drop_column("connector_definitions", "api_config")

    # Drop new tables
    _drop_rls("connector_tasks")
    op.drop_table("connector_tasks")

    _drop_rls("connector_oauth_states")
    op.drop_table("connector_oauth_states")

    _drop_rls("connector_app_credentials")
    op.drop_table("connector_app_credentials")
