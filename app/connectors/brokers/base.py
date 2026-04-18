"""CredentialBroker interface (P2.1).

Abstracts the "service a connector tool call" operation so the app runtime
never touches raw tokens. Two implementations:

* **InHouseBroker** — wraps the existing ``app.connectors.oauth_flow`` +
  ``credentials`` + ``executor`` chain with Vault/KMS-backed token storage.
* **ComposioBroker** — delegates OAuth + tool execution to Composio's
  managed platform. Tokens live in Composio's vault and never enter
  the agent runtime.

The agent bridge always routes through the broker interface, so adding
new brokers (Nango, Paragon, Arcade, etc.) is a drop-in exercise.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import ConnectorDefinition, TenantConnection


@dataclass(frozen=True)
class AuthorizationStart:
    """Result of kicking off an OAuth flow through a broker."""

    auth_url: str
    state: str


@dataclass(frozen=True)
class ToolDescriptor:
    """Platform-format tool descriptor returned by a broker."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    source: str = "connector"
    trust_level: str = "untrusted"


@dataclass(frozen=True)
class ToolResult:
    """Result of a tool invocation through a broker."""

    content: Any
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class CredentialBroker(ABC):
    """Service OAuth + tool invocation for one class of connectors."""

    name: str = "abstract"

    @abstractmethod
    async def start_authorization(
        self,
        *,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        redirect_uri: str,
        db: AsyncSession,
    ) -> AuthorizationStart:
        """Begin the OAuth flow. Returns the auth URL and state token."""

    @abstractmethod
    async def complete_authorization(
        self,
        *,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        code: str,
        state: str,
        redirect_uri: str,
        db: AsyncSession,
    ) -> TenantConnection:
        """Exchange the authorization code and persist a connection row."""

    @abstractmethod
    async def list_tools(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
    ) -> list[ToolDescriptor]:
        """Return the tools available for this connection + user."""

    @abstractmethod
    async def invoke_tool(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
        actor_user_id: uuid.UUID | None = None,
        agent_instance_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Invoke a tool. Returns the normalized result dict.

        Implementations are responsible for rate limiting, auth injection,
        and provider error normalization. Tokens must never be returned or
        logged in the result.
        """

    @abstractmethod
    async def revoke_connection(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
    ) -> None:
        """Revoke an active connection."""
