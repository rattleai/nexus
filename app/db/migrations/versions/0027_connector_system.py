"""Connector system: replace cloud_connections with unified connector tables.

Drops the legacy cloud_connections table and CloudProvider enum.
Creates: connector_definitions, tenant_connections, tenant_credentials,
         connector_audit_logs.
Updates data_sources to reference tenant_connections instead.

Revision ID: 0027_connector_system
Revises: 0026_cpq_rls_with_check
Create Date: 2026-03-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB, UUID

revision = "0027_connector_system"
down_revision = "0026_cpq_rls_with_check"
branch_labels = None
depends_on = None

TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _rls(table: str) -> None:
    """Enable RLS with USING + WITH CHECK and FORCE."""
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
    # ── 1. Create enum types ──────────────────────────────────────────
    # Use ``postgresql.ENUM`` with ``create_type=False`` so SQLAlchemy's
    # DDL emitter never auto-creates the types when they're referenced in
    # column definitions. We create them exactly once per migration via
    # explicit ``.create(checkfirst=True)`` calls below — this avoids the
    # "type connectortype already exists" DuplicateObjectError that
    # sa.Enum() triggers when the same instance is reused in create_table.

    connector_type_enum = PG_ENUM(
        "mcp_server", "oauth_api", "api_key_api", "webhook",
        name="connectortype",
        create_type=False,
    )
    connector_type_enum.create(op.get_bind(), checkfirst=True)

    auth_type_enum = PG_ENUM(
        "oauth2", "api_key", "bearer_token", "none",
        name="authtype",
        create_type=False,
    )
    auth_type_enum.create(op.get_bind(), checkfirst=True)

    connection_status_enum = PG_ENUM(
        "active", "degraded", "expired", "disconnected", "error",
        name="connectionstatus",
        create_type=False,
    )
    connection_status_enum.create(op.get_bind(), checkfirst=True)

    credential_type_enum = PG_ENUM(
        "oauth2", "api_key", "bearer_token", "custom",
        name="credentialtype",
        create_type=False,
    )
    credential_type_enum.create(op.get_bind(), checkfirst=True)

    # ── 2. Create connector_definitions (global catalog) ──────────────

    op.create_table(
        "connector_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("icon", sa.String(100), server_default="Plug"),
        sa.Column("category", sa.String(50), server_default="custom", index=True),
        sa.Column("connector_type", connector_type_enum, nullable=False),
        sa.Column("auth_type", auth_type_enum, nullable=False),
        sa.Column("auth_config", JSONB, nullable=True),
        sa.Column("mcp_config", JSONB, nullable=True),
        sa.Column("tool_definitions", JSONB, nullable=True),
        sa.Column("webhook_config", JSONB, nullable=True),
        sa.Column("capability_template", JSONB, nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default="false"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("version", sa.String(50), server_default="1.0"),
        sa.Column("documentation_url", sa.String(2048), nullable=True),
        sa.Column("tags", JSONB, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── 3. Create tenant_connections ──────────────────────────────────

    op.create_table(
        "tenant_connections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connector_definition_id", UUID(as_uuid=True), sa.ForeignKey("connector_definitions.id"), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("account_identifier", sa.String(255), nullable=True),
        sa.Column("status", connection_status_enum, server_default="active"),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("mcp_session_id", sa.String(255), nullable=True),
        sa.Column("mcp_tools_cache", JSONB, nullable=True),
        sa.Column("mcp_resources_cache", JSONB, nullable=True),
        sa.Column("cache_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_status", JSONB, nullable=True),
        sa.Column("health_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config_overrides", JSONB, server_default="{}"),
        sa.Column("connected_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "connector_definition_id", "account_identifier",
            name="uq_tenant_connection_account",
        ),
    )
    op.create_index("ix_tenant_connections_tenant_status", "tenant_connections", ["tenant_id", "status"])
    op.create_index("ix_tenant_connections_tenant_connector", "tenant_connections", ["tenant_id", "connector_definition_id"])

    _rls("tenant_connections")

    # ── 4. Create tenant_credentials ──────────────────────────────────

    op.create_table(
        "tenant_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connection_id", UUID(as_uuid=True), sa.ForeignKey("tenant_connections.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("credential_type", credential_type_enum, nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_scopes", JSONB, nullable=True),
        sa.Column("auth_metadata", JSONB, nullable=True),
        sa.Column("api_key_enc", sa.Text(), nullable=True),
        sa.Column("is_valid", sa.Boolean(), server_default="true"),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenant_credentials_tenant", "tenant_credentials", ["tenant_id"])

    _rls("tenant_credentials")

    # ── 5. Create connector_audit_logs ────────────────────────────────

    op.create_table(
        "connector_audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connection_id", UUID(as_uuid=True), sa.ForeignKey("tenant_connections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("tool_name", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=True),
        sa.Column("agent_instance_id", UUID(as_uuid=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_summary", JSONB, nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_connector_audit_tenant_time", "connector_audit_logs", ["tenant_id", "occurred_at"])
    op.create_index("ix_connector_audit_connection_time", "connector_audit_logs", ["tenant_id", "connection_id", "occurred_at"])

    _rls("connector_audit_logs")

    # ── 6. Update data_sources: replace cloud_connection_id → connection_id ─

    # Add new column referencing tenant_connections
    op.add_column(
        "data_sources",
        sa.Column("connection_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenant_connections.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.add_column(
        "data_sources",
        sa.Column("connector_slug", sa.String(100), nullable=True),
    )

    # Drop old columns and FK
    op.drop_constraint(
        "data_sources_cloud_connection_id_fkey", "data_sources", type_="foreignkey",
    )
    op.drop_column("data_sources", "cloud_connection_id")
    op.drop_column("data_sources", "cloud_provider")

    # ── 7. Drop legacy cloud_connections table ────────────────────────

    _drop_rls("cloud_connections")
    op.drop_table("cloud_connections")

    # Drop the CloudProvider enum type
    sa.Enum(name="cloudprovider").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Recreate CloudProvider enum
    cloud_provider_enum = sa.Enum(
        "google_drive", "dropbox", "onedrive",
        name="cloudprovider",
    )
    cloud_provider_enum.create(op.get_bind(), checkfirst=True)

    # Recreate cloud_connections table
    op.create_table(
        "cloud_connections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("provider", cloud_provider_enum, nullable=False),
        sa.Column("account_email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Restore data_sources columns
    op.add_column("data_sources", sa.Column("cloud_provider", cloud_provider_enum, nullable=True))
    op.add_column("data_sources", sa.Column("cloud_connection_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "data_sources_cloud_connection_id_fkey",
        "data_sources", "cloud_connections",
        ["cloud_connection_id"], ["id"],
    )
    op.drop_column("data_sources", "connector_slug")
    op.drop_column("data_sources", "connection_id")

    # Drop connector tables
    _drop_rls("connector_audit_logs")
    op.drop_table("connector_audit_logs")

    _drop_rls("tenant_credentials")
    op.drop_table("tenant_credentials")

    _drop_rls("tenant_connections")
    op.drop_table("tenant_connections")

    op.drop_table("connector_definitions")

    # Drop new enum types
    sa.Enum(name="credentialtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="connectionstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="authtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="connectortype").drop(op.get_bind(), checkfirst=True)
