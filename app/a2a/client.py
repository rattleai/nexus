"""A2A client adapter (P3.2).

Wraps a remote A2A agent as a ``CredentialBroker`` so existing agent
tooling can invoke it just like any other connector. When the A2A feature
flag is off this module is not imported by the broker router, keeping
the hot path free of A2A overhead.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.brokers.base import (
    AuthorizationStart,
    CredentialBroker,
    ToolDescriptor,
)
from app.connectors.models import ConnectorDefinition, TenantConnection

logger = structlog.stdlib.get_logger()


class A2ABroker(CredentialBroker):
    """Broker that proxies tool calls to a remote A2A agent."""

    name = "a2a"

    async def start_authorization(
        self,
        *,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        redirect_uri: str,
        db: AsyncSession,
    ) -> AuthorizationStart:
        raise NotImplementedError("A2A connectors authenticate via tenant app credentials")

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
        raise NotImplementedError

    async def list_tools(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
    ) -> list[ToolDescriptor]:
        card = await self._fetch_agent_card(connector_def)
        if card is None:
            return []
        descriptors: list[ToolDescriptor] = []
        for cap in card.get("capabilities", []):
            descriptors.append(
                ToolDescriptor(
                    name=f"connector:{connector_def.slug}:{cap.get('name', '')}",
                    description=cap.get("description", "") or "",
                    input_schema={},
                    trust_level=connector_def.trust_level.value,
                )
            )
        return descriptors

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
        url = (connector_def.mcp_config or {}).get("server_url", "")
        if not url:
            return {"error": "A2A connector has no server URL", "is_error": True}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{url.rstrip('/')}/message/send",
                    json={
                        "capability": tool_name,
                        "input": arguments,
                        "context": {"tenant_id": str(tenant_id)},
                    },
                )
            resp.raise_for_status()
            return {"content": resp.json(), "is_error": False}
        except Exception as exc:
            return {
                "error": f"A2A call failed: {str(exc)[:200]}",
                "is_error": True,
            }

    async def revoke_connection(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
    ) -> None:
        pass

    async def _fetch_agent_card(
        self, connector_def: ConnectorDefinition,
    ) -> dict[str, Any] | None:
        url = (connector_def.mcp_config or {}).get("server_url", "")
        if not url:
            return None
        card_url = f"{url.rstrip('/')}/.well-known/agent.json"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(card_url)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            logger.debug("a2a_card_fetch_failed", exc_info=True)
        return None


a2a_broker = A2ABroker()
