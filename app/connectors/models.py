"""SQLAlchemy models for the connector system.

All tenant-scoped models use RLS (tenant_id column + set_tenant_context).
ConnectorDefinition is a global catalog (no tenant_id) — visible to all tenants.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


# ── Enums ──────────────────────────────────────────────────


class ConnectorType(enum.StrEnum):
    MCP_SERVER = "mcp_server"
    OAUTH_API = "oauth_api"
    API_KEY_API = "api_key_api"
    WEBHOOK = "webhook"


class AuthType(enum.StrEnum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    NONE = "none"


class ConnectionStatus(enum.StrEnum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    EXPIRED = "expired"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class CredentialType(enum.StrEnum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    CUSTOM = "custom"


class TrustLevel(enum.StrEnum):
    """Trust tier for a connector definition.

    Determines whether a connector's tool descriptions are passed through
    to the LLM verbatim (verified), with admin-approved overrides (trusted),
    or replaced with generic stubs (untrusted) to prevent prompt injection.
    """

    VERIFIED = "verified"
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class BrokerType(enum.StrEnum):
    """Credential broker backing a connector.

    Composio manages OAuth + rate limiting + the tool catalog; tokens never
    enter the app runtime. In-house uses app.connectors.* directly with
    per-tenant Vault/KMS-backed encrypted storage.
    """

    COMPOSIO = "composio"
    IN_HOUSE = "in_house"


class ConnectorTaskStatus(enum.StrEnum):
    """MCP 2025-11-25 Tasks primitive — lifecycle states."""

    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── Connector Definition (global catalog) ──────────────────


class ConnectorDefinition(TimestampMixin, Base):
    """A type of connector that can be instantiated per-tenant.

    System-shipped connectors are loaded from YAML files in
    ``app/connectors/builtin/`` at startup.  Tenants can also
    register custom MCP server URLs or API connectors.
    """

    __tablename__ = "connector_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    # Display
    icon: Mapped[str] = mapped_column(String(100), default="Plug")
    category: Mapped[str] = mapped_column(String(50), default="custom", index=True)

    # Type & auth
    connector_type: Mapped[ConnectorType] = mapped_column(
        Enum(ConnectorType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    auth_type: Mapped[AuthType] = mapped_column(
        Enum(AuthType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    # OAuth configuration (when auth_type = 'oauth2')
    # {authorize_url, token_url, scopes, pkce_required, token_endpoint_auth_method}
    # NOTE: client_id / client_secret are NEVER stored here — they live in
    # ConnectorAppCredential (per-tenant, encrypted). Keeping secrets in this
    # global catalog would share them across every tenant.
    auth_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # MCP server configuration (when connector_type = 'mcp_server')
    # {server_url, transport: "streamable_http"|"stdio", command, args, env}
    mcp_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # HTTP API configuration (when connector_type = 'oauth_api' | 'api_key_api')
    # {api_base_url, rate_limit_header, default_headers}
    api_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Tool definitions for non-MCP connectors
    # [{name, description, input_schema, method, path, arg_location}]
    tool_definitions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Webhook configuration (when connector_type = 'webhook')
    # {signature_header, signature_algo, events}
    # NOTE: webhook secret is NEVER stored here — lives in ConnectorAppCredential.
    webhook_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Capability template for auto-generating capability domains
    # {groups: [{slug_suffix, label, tool_patterns: [...]}]}
    capability_template: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # RFC 9728/8414/7591 OAuth discovery cache
    # {authorize_url, token_url, registration_endpoint, scopes_supported, ...}
    discovery_cache: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    discovery_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # RFC 7591 Dynamic Client Registration endpoint (populated by discovery)
    registration_endpoint: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Trust tier — gates whether tool descriptions are passed through verbatim
    trust_level: Mapped[TrustLevel] = mapped_column(
        Enum(TrustLevel, name="trustlevel", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=TrustLevel.UNTRUSTED.value,
    )

    # Credential broker — routes OAuth + tool invocation through Composio or in-house
    broker: Mapped[BrokerType] = mapped_column(
        Enum(BrokerType, name="brokertype", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=BrokerType.IN_HOUSE.value,
    )

    # Whether this connector requires the tenant to register their own OAuth app
    # (client_id / client_secret) before users can authenticate. Set True for
    # providers that do not support RFC 7591 Dynamic Client Registration.
    requires_app_credentials: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )

    # Metadata
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str] = mapped_column(String(50), default="1.0")
    documentation_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSONB, default=list)

    # Relationships
    connections: Mapped[list[TenantConnection]] = relationship(
        back_populates="connector_definition",
        cascade="all, delete-orphan",
    )


# ── Tenant Connection (per-tenant instance) ─────────────────


class TenantConnection(SoftDeleteMixin, TimestampMixin, Base):
    """An authenticated connection from a tenant to a connector.

    Each row represents one tenant having connected to one connector
    (e.g. "Acme Corp connected to Google Workspace as user@acme.com").
    """

    __tablename__ = "tenant_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True,
    )
    connector_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connector_definitions.id"), nullable=False,
    )

    # Display
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_identifier: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )

    # Status
    status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, values_callable=lambda e: [m.value for m in e]),
        default=ConnectionStatus.ACTIVE,
    )
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # MCP session state
    mcp_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mcp_tools_cache: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mcp_resources_cache: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mcp_prompts_cache: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mcp_capabilities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cache_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Health monitoring
    health_status: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    health_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Per-connection configuration overrides
    config_overrides: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Tracking
    connected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Relationships
    connector_definition: Mapped[ConnectorDefinition] = relationship(
        back_populates="connections",
    )
    credential: Mapped[TenantCredential | None] = relationship(
        back_populates="connection",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connector_definition_id", "connected_by_user_id",
            "account_identifier",
            name="uq_tenant_connection_user_account",
        ),
        Index("ix_tenant_connections_tenant_status", "tenant_id", "status"),
        Index(
            "ix_tenant_connections_tenant_connector",
            "tenant_id", "connector_definition_id",
        ),
    )


# ── Tenant Credential (encrypted secrets) ───────────────────


class TenantCredential(TimestampMixin, Base):
    """Encrypted credential storage for a tenant connection.

    All token/key fields are encrypted via ``app.core.encryption``
    before being persisted.  Never return these fields in API responses.
    """

    __tablename__ = "tenant_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant_connections.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    credential_type: Mapped[CredentialType] = mapped_column(
        Enum(CredentialType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    # OAuth2 fields (encrypted)
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    granted_scopes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Non-sensitive OAuth metadata
    auth_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # API key / bearer token (encrypted)
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    refresh_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    connection: Mapped[TenantConnection] = relationship(
        back_populates="credential",
    )

    __table_args__ = (
        Index("ix_tenant_credentials_tenant", "tenant_id"),
    )


# ── Connector Audit Log (append-only) ───────────────────────


class ConnectorAuditLog(Base):
    """Append-only log of connector operations for compliance and debugging."""

    __tablename__ = "connector_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False,
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenant_connections.id", ondelete="SET NULL"), nullable=True,
    )

    # What happened
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Who did it
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )

    # Execution details
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Timestamp
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_connector_audit_tenant_time", "tenant_id", "occurred_at"),
        Index(
            "ix_connector_audit_connection_time",
            "tenant_id", "connection_id", "occurred_at",
        ),
    )


# ── Per-Tenant OAuth App Credentials (P0.1) ─────────────────


class ConnectorAppCredential(TimestampMixin, Base):
    """Per-tenant OAuth app client_id / client_secret / webhook secret.

    Replaces the insecure pattern of storing OAuth app credentials in the
    global ``connector_definitions.auth_config`` JSONB. Each tenant registers
    its own OAuth application for each connector slug; secrets are encrypted
    at rest via ``app.core.encryption`` and isolated by RLS.
    """

    __tablename__ = "connector_app_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True,
    )
    connector_slug: Mapped[str] = mapped_column(String(100), nullable=False)

    # Encrypted secrets (Fernet v1 or AES-256-GCM v2, versioned)
    client_id_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional per-tenant redirect URI override (for providers that need
    # exact redirect URI matching)
    redirect_uri_override: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Additional connector-specific config (non-secret)
    extra_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Audit: which user registered the app
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connector_slug",
            name="uq_connector_app_credentials_tenant_slug",
        ),
        Index("ix_connector_app_credentials_tenant", "tenant_id"),
    )


# ── Durable OAuth State (P0.5) ───────────────────────────────


class ConnectorOAuthState(Base):
    """Durable OAuth state token store.

    OAuth state tokens survive Redis restart by being persisted here.
    Redis remains a read-through cache; on miss, we fall back to this table.
    """

    __tablename__ = "connector_oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False,
    )
    state_token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    connector_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_enc: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_connector_oauth_states_tenant", "tenant_id"),
        Index("ix_connector_oauth_states_expires", "expires_at"),
    )


# ── Async MCP Task Handles (P1.1) ────────────────────────────


class ConnectorTask(TimestampMixin, Base):
    """MCP 2025-11-25 Tasks primitive — async tool-call handles.

    When an MCP server returns a task handle instead of an immediate result
    (e.g., long-running operations), a row is created here and the agent
    runtime polls via get_task_status or waits for a webhook push.
    """

    __tablename__ = "connector_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant_connections.id", ondelete="CASCADE"), nullable=False,
    )

    # Handle issued by the MCP server
    mcp_task_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    arguments: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Lifecycle
    status: Mapped[ConnectorTaskStatus] = mapped_column(
        Enum(
            ConnectorTaskStatus,
            name="connectortaskstatus",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        server_default=ConnectorTaskStatus.WORKING.value,
    )
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When status is input_required, this holds the server-requested prompt
    input_required: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Audit
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    agent_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("ix_connector_tasks_tenant_status", "tenant_id", "status"),
        Index("ix_connector_tasks_connection", "connection_id"),
    )
