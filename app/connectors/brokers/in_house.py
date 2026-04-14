"""In-house credential broker (P2.3).

Wraps the existing ``app.connectors.oauth_flow`` + ``credentials`` +
``executor`` chain behind the ``CredentialBroker`` interface. Used for:

* Custom MCP servers a tenant registers
* Sensitive/compliance connectors where tokens must stay in-house
* Providers not covered by Composio's catalog

Token encryption delegates to ``app.connectors.vault`` which transparently
uses HashiCorp Vault Transit when ``VAULT_ADDR`` is set, falling back to
the existing ``app.core.encryption`` envelope encryption otherwise.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.brokers.base import (
    AuthorizationStart,
    CredentialBroker,
    ToolDescriptor,
    ToolResult,
)
from app.connectors.executor import connector_executor
from app.connectors.models import ConnectorDefinition, TenantConnection
from app.connectors.oauth_flow import oauth_flow
from app.connectors.tool_adapter import ConnectorToolAdapter

logger = structlog.stdlib.get_logger()


class InHouseBroker(CredentialBroker):
    """Broker that runs OAuth + tool invocation directly in the app process."""

    name = "in_house"

    async def start_authorization(
        self,
        *,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        redirect_uri: str,
        db: AsyncSession,
    ) -> AuthorizationStart:
        result = await oauth_flow.start(
            connector_def=connector_def,
            tenant_id=tenant_id,
            redirect_uri=redirect_uri,
            user_id=actor_user_id,
            db=db,
        )
        return AuthorizationStart(
            auth_url=result["auth_url"],
            state=result["state"],
        )

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
        return await oauth_flow.callback(
            connector_def=connector_def,
            code=code,
            state=state,
            tenant_id=tenant_id,
            redirect_uri=redirect_uri,
            db=db,
        )

    async def list_tools(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
    ) -> list[ToolDescriptor]:
        platform_tools = ConnectorToolAdapter.connection_tools_to_platform(
            connection, connector_def,
        )
        return [
            ToolDescriptor(
                name=t["name"],
                description=t["description"],
                input_schema=t["input_schema"] or {},
                trust_level=t.get("trust_level", "untrusted"),
            )
            for t in platform_tools
        ]

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
        from app.connectors.durable import durable_invoke_tool

        return await durable_invoke_tool(
            connection=connection,
            connector_def=connector_def,
            tool_name=tool_name,
            arguments=arguments,
            tenant_id=tenant_id,
            db=db,
            actor_user_id=actor_user_id,
            agent_instance_id=agent_instance_id,
            idempotency_key=idempotency_key,
        )

    async def revoke_connection(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
    ) -> None:
        from app.connectors.credentials import credential_manager

        if connection.credential is not None:
            await credential_manager.revoke(connection.credential, connector_def, db)


in_house_broker = InHouseBroker()
