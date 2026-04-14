"""Shared fixtures for connector tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.models import (
    AuthType,
    BrokerType,
    ConnectionStatus,
    ConnectorDefinition,
    ConnectorType,
    CredentialType,
    TenantConnection,
    TenantCredential,
    TrustLevel,
)


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def alt_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_a_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_b_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def slack_oauth_connector() -> ConnectorDefinition:
    """A Slack-like OAuth API connector definition (in-memory)."""
    cd = ConnectorDefinition(
        id=uuid.uuid4(),
        slug="slack",
        name="Slack",
        description="Slack connector",
        icon="MessageSquare",
        category="communication",
        connector_type=ConnectorType.OAUTH_API,
        auth_type=AuthType.OAUTH2,
        auth_config={
            "authorize_url": "https://slack.com/oauth/v2/authorize",
            "token_url": "https://slack.com/api/oauth.v2.access",
            "userinfo_url": "https://slack.com/api/auth.test",
            "pkce_required": True,
            "scopes": ["channels:read", "chat:write"],
        },
        api_config={
            "api_base_url": "https://slack.com/api",
        },
        tool_definitions=[
            {
                "name": "list_channels",
                "description": "List channels",
                "method": "GET",
                "path": "/conversations.list",
                "arg_location": "query",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "send_message",
                "description": "Send a message",
                "method": "POST",
                "path": "/chat.postMessage",
                "arg_location": "json_body",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["channel", "text"],
                },
            },
        ],
        trust_level=TrustLevel.VERIFIED,
        broker=BrokerType.IN_HOUSE,
        requires_app_credentials=True,
        is_system=True,
        is_active=True,
        version="1.0.0",
        tags=[],
    )
    return cd


@pytest.fixture
def untrusted_mcp_connector() -> ConnectorDefinition:
    cd = ConnectorDefinition(
        id=uuid.uuid4(),
        slug="evil-mcp",
        name="Evil MCP",
        description="An unverified MCP server",
        icon="Server",
        category="custom",
        connector_type=ConnectorType.MCP_SERVER,
        auth_type=AuthType.NONE,
        mcp_config={"transport": "streamable_http", "server_url": "https://example.invalid/mcp"},
        trust_level=TrustLevel.UNTRUSTED,
        broker=BrokerType.IN_HOUSE,
        is_system=False,
        is_active=True,
        version="1.0.0",
        tags=[],
    )
    return cd


def make_connection(
    tenant_id: uuid.UUID,
    connector_def: ConnectorDefinition,
    user_id: uuid.UUID | None,
    account_identifier: str = "alice@example.com",
) -> TenantConnection:
    now = datetime.now(UTC)
    conn = TenantConnection(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        connector_definition_id=connector_def.id,
        display_name=account_identifier,
        account_identifier=account_identifier,
        status=ConnectionStatus.ACTIVE,
        connected_by_user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    conn.connector_definition = connector_def
    return conn


def make_oauth_credential(
    tenant_id: uuid.UUID,
    connection: TenantConnection,
    *,
    expired: bool = False,
) -> TenantCredential:
    from app.core.encryption import encrypt

    now = datetime.now(UTC)
    cred = TenantCredential(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        connection_id=connection.id,
        credential_type=CredentialType.OAUTH2,
        access_token_enc=encrypt("test-access-token"),
        refresh_token_enc=encrypt("test-refresh-token"),
        token_expires_at=(
            now - timedelta(minutes=5) if expired else now + timedelta(hours=1)
        ),
        is_valid=True,
        granted_scopes={"scopes": ["channels:read"]},
        auth_metadata={},
        created_at=now,
        updated_at=now,
    )
    connection.credential = cred
    return cred


@pytest.fixture
def mock_db():
    """Minimal async DB stub that records add/flush calls."""
    db = MagicMock()
    db.add = MagicMock()
    db.delete = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock()
    return db
