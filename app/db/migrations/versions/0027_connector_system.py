"""Connector system: replace cloud_connections with unified connector tables.

Drops the legacy cloud_connections table and CloudProvider enum.
Creates: connector_definitions, tenant_connections, tenant_credentials,
         connector_audit_logs.
Updates data_sources to reference tenant_connections instead.

Revision ID: 0027_connector_system
Revises: 0001_basic_schema
Create Date: 2026-03-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB, UUID

revision = "0027_connector_system"
down_revision = "0001_basic_schema"
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
        "mcp_server",
        "oauth_api",
        "api_key_api",
        "webhook",
        name="connectortype",
        create_type=False,
    )
    connector_type_enum.create(op.get_bind(), checkfirst=True)

    auth_type_enum = PG_ENUM(
        "oauth2",
        "api_key",
        "bearer_token",
        "none",
        name="authtype",
        create_type=False,
    )
    auth_type_enum.create(op.get_bind(), checkfirst=True)

    connection_status_enum = PG_ENUM(
        "active",
        "degraded",
        "expired",
        "disconnected",
        "error",
        name="connectionstatus",
        create_type=False,
    )
    connection_status_enum.create(op.get_bind(), checkfirst=True)

    credential_type_enum = PG_ENUM(
        "oauth2",
        "api_key",
        "bearer_token",
        "custom",
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
        sa.Column(
            "connector_definition_id", UUID(as_uuid=True), sa.ForeignKey("connector_definitions.id"), nullable=False
        ),
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
            "tenant_id",
            "connector_definition_id",
            "account_identifier",
            name="uq_tenant_connection_account",
        ),
    )
    op.create_index("ix_tenant_connections_tenant_status", "tenant_connections", ["tenant_id", "status"])
    op.create_index(
        "ix_tenant_connections_tenant_connector", "tenant_connections", ["tenant_id", "connector_definition_id"]
    )

    _rls("tenant_connections")

    # ── 4. Create tenant_credentials ──────────────────────────────────

    op.create_table(
        "tenant_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "connection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenant_connections.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
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
        sa.Column(
            "connection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenant_connections.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index(
        "ix_connector_audit_connection_time", "connector_audit_logs", ["tenant_id", "connection_id", "occurred_at"]
    )

    _rls("connector_audit_logs")

    # ── 6. Update data_sources: replace cloud_connection_id → connection_id ─

    # Add new column referencing tenant_connections
    op.add_column(
        "data_sources",
        sa.Column(
            "connection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenant_connections.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "data_sources",
        sa.Column("connector_slug", sa.String(100), nullable=True),
    )

    # ── 6b. Backfill: copy existing cloud_connections rows into the new
    # connector system before the drop so tenant OAuth tokens are not lost.
    # Runs in a single SQL pass and is a no-op on fresh DBs (WHERE false
    # short-circuits when the source table is empty). Idempotent: re-running
    # the migration would only create connector_definitions once due to the
    # ON CONFLICT clause.
    _backfill_cloud_connections_to_tenant_connections()

    # Drop old columns and FK
    op.drop_constraint(
        "data_sources_cloud_connection_id_fkey",
        "data_sources",
        type_="foreignkey",
    )
    op.drop_column("data_sources", "cloud_connection_id")
    op.drop_column("data_sources", "cloud_provider")

    # ── 7. Drop legacy cloud_connections table ────────────────────────

    _drop_rls("cloud_connections")
    op.drop_table("cloud_connections")

    # Drop the CloudProvider enum type
    sa.Enum(name="cloudprovider").drop(op.get_bind(), checkfirst=True)


def _backfill_cloud_connections_to_tenant_connections() -> None:
    """Migrate cloud_connections rows → connector_definitions + tenant_connections.

    Maps legacy ``CloudProvider`` values to connector_definition slugs:
      ``google_drive`` → ``google-workspace``
      ``dropbox``      → ``dropbox``
      ``onedrive``     → ``onedrive``

    Inserts minimal connector_definitions rows so FK references resolve; the
    startup ``sync_builtins`` pass will fill in the full manifest metadata
    on first boot. Existing connector_definitions rows (from a prior run of
    this migration) are preserved via ON CONFLICT DO NOTHING.
    """
    bind = op.get_bind()
    # Skip if the legacy table was already dropped (e.g. second run of the
    # migration on a DB that never had the table in the first place).
    has_legacy = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'cloud_connections')"
        )
    ).scalar()
    if not has_legacy:
        return

    # 1. Seed the three cloud-drive connector_definitions rows so that
    # tenant_connections.connector_definition_id has something to reference.
    # Minimal column set — this migration predates 0028 (broker / trust_level
    # / requires_app_credentials) and 0029 (source / aliases). Startup
    # ``sync_builtins`` fills in the full manifest on next boot.
    bind.execute(
        sa.text(
            """
            INSERT INTO connector_definitions
                (slug, name, description, icon, category, connector_type,
                 auth_type, version, documentation_url, is_active)
            VALUES
                ('dropbox', 'Dropbox',
                 'Connect to Dropbox for cloud file storage and sharing.',
                 'HardDrive', 'cloud_storage', 'oauth_api', 'oauth2',
                 '1.0.0',
                 'https://www.dropbox.com/developers/documentation', true),
                ('google-workspace', 'Google Workspace',
                 'Connect to Google Workspace (Drive, Gmail, Calendar).',
                 'Mail', 'productivity', 'mcp_server', 'oauth2',
                 '1.0.0',
                 'https://developers.google.com/workspace', true),
                ('onedrive', 'OneDrive',
                 'Connect to Microsoft OneDrive via Graph API.',
                 'Cloud', 'cloud_storage', 'oauth_api', 'oauth2',
                 '1.0.0',
                 'https://learn.microsoft.com/en-us/onedrive/developer/', true)
            ON CONFLICT (slug) DO NOTHING
            """
        )
    )

    # 2. Backfill tenant_connections from cloud_connections. Legacy
    # provider strings map 1:1 to new slugs except google_drive →
    # google-workspace. The tenant_connections id is preserved so the
    # data_sources.connection_id backfill (step 4) can reuse the same
    # UUID as the old cloud_connection_id.
    bind.execute(
        sa.text(
            """
            INSERT INTO tenant_connections
                (id, tenant_id, connector_definition_id, display_name,
                 account_identifier, status,
                 created_at, updated_at, deleted_at)
            SELECT
                cc.id,
                cc.tenant_id,
                cd.id,
                COALESCE(cc.display_name, cc.account_email),
                cc.account_email,
                CASE WHEN cc.is_active THEN 'active'::connectionstatus
                     ELSE 'disconnected'::connectionstatus END,
                cc.created_at,
                cc.updated_at,
                cc.deleted_at
            FROM cloud_connections cc
            JOIN connector_definitions cd
              ON cd.slug = CASE cc.provider::text
                               WHEN 'google_drive' THEN 'google-workspace'
                               WHEN 'dropbox'      THEN 'dropbox'
                               WHEN 'onedrive'     THEN 'onedrive'
                           END
            ON CONFLICT (id) DO NOTHING
            """
        )
    )

    # 3. Backfill tenant_credentials. Tokens are already encrypted with the
    # same key, so we copy the ciphertext verbatim into the new columns
    # (access_token_enc / refresh_token_enc).
    bind.execute(
        sa.text(
            """
            INSERT INTO tenant_credentials
                (tenant_id, connection_id, credential_type,
                 access_token_enc, refresh_token_enc, token_expires_at,
                 granted_scopes, is_valid, created_at, updated_at)
            SELECT
                cc.tenant_id,
                cc.id,
                'oauth2'::credentialtype,
                cc.access_token_encrypted,
                cc.refresh_token_encrypted,
                cc.token_expires_at,
                cc.scopes,
                true,
                cc.created_at,
                cc.updated_at
            FROM cloud_connections cc
            WHERE NOT EXISTS (
                SELECT 1 FROM tenant_credentials tc
                WHERE tc.connection_id = cc.id
            )
            """
        )
    )

    # 4. Point data_sources.connection_id at the new tenant_connections row
    # (same UUID is preserved) and set connector_slug.
    bind.execute(
        sa.text(
            """
            UPDATE data_sources ds
            SET connection_id = ds.cloud_connection_id,
                connector_slug = CASE ds.cloud_provider::text
                                     WHEN 'google_drive' THEN 'google-workspace'
                                     WHEN 'dropbox'      THEN 'dropbox'
                                     WHEN 'onedrive'     THEN 'onedrive'
                                 END
            WHERE ds.cloud_connection_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    # Recreate CloudProvider enum
    cloud_provider_enum = sa.Enum(
        "google_drive",
        "dropbox",
        "onedrive",
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
        "data_sources",
        "cloud_connections",
        ["cloud_connection_id"],
        ["id"],
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
