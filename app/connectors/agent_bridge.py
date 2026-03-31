"""Agent Bridge: integrates connector tools with the agent ToolRegistry.

Provides ``ConnectorToolProvider`` which the ToolRegistry calls to
list and invoke connector tools alongside built-in and tenant tools.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import settings
from app.connectors.models import (
    ConnectionStatus,
    ConnectorDefinition,
    TenantConnection,
)
from app.connectors.tool_adapter import (
    ConnectorToolAdapter,
    parse_tool_name,
)

logger = structlog.stdlib.get_logger()


class ConnectorToolProvider:
    """Provides connector tools to the agent ToolRegistry.

    Called by ``ToolRegistry.list_all_tools()`` and ``ToolRegistry.invoke()``
    to include connector-sourced tools in the agent's available tool set.
    """

    async def list_tools(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Return all tools from the tenant's active connections.

        First checks the Redis cache, then falls back to the database.
        Each tool is returned in the platform format with a namespaced
        name: ``connector:{slug}:{tool_name}``.
        """
        # Try Redis cache first
        from app.connectors.cache import connector_tool_cache

        cached = await connector_tool_cache.get_tools(tenant_id)
        if cached is not None:
            return cached

        # Cache miss — load from database
        tools = await self._load_tools_from_db(tenant_id, db)

        # Populate cache
        await connector_tool_cache.set_tools(tenant_id, tools)

        return tools

    async def _load_tools_from_db(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Load tools from active connections in the database."""
        result = await db.execute(
            select(TenantConnection)
            .where(
                TenantConnection.tenant_id == tenant_id,
                TenantConnection.status == ConnectionStatus.ACTIVE,
                TenantConnection.deleted_at.is_(None),
            )
            .options(joinedload(TenantConnection.connector_definition))
        )
        connections = result.unique().scalars().all()

        all_tools: list[dict[str, Any]] = []
        for conn in connections:
            cd = conn.connector_definition
            if not cd or not cd.is_active:
                continue

            tools = ConnectorToolAdapter.connection_tools_to_platform(conn, cd)
            all_tools.extend(tools)

        return all_tools

    async def invoke(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
        agent_instance_id: uuid.UUID | None = None,
    ) -> Any:
        """Invoke a connector tool by its namespaced name.

        Parses ``connector:{slug}:{tool}``, resolves the connection,
        injects credentials, and delegates to the ConnectorExecutor.
        """
        # Parse the namespaced tool name
        try:
            connector_slug, original_tool = parse_tool_name(tool_name)
        except ValueError:
            return {"error": f"Invalid connector tool name: {tool_name}"}

        # Look up the connection
        result = await db.execute(
            select(TenantConnection)
            .join(ConnectorDefinition)
            .where(
                TenantConnection.tenant_id == tenant_id,
                TenantConnection.status == ConnectionStatus.ACTIVE,
                TenantConnection.deleted_at.is_(None),
                ConnectorDefinition.slug == connector_slug,
            )
            .options(
                joinedload(TenantConnection.connector_definition),
                joinedload(TenantConnection.credential),
            )
        )
        connection = result.unique().scalar_one_or_none()

        if not connection:
            return {
                "error": f"No active connection for connector '{connector_slug}'. "
                "The user may need to connect this service first.",
            }

        connector_def = connection.connector_definition

        # Delegate to the executor
        from app.connectors.executor import connector_executor

        return await connector_executor.invoke(
            connection=connection,
            connector_def=connector_def,
            tool_name=original_tool,
            arguments=arguments,
            tenant_id=tenant_id,
            db=db,
            actor_type="agent",
            agent_instance_id=agent_instance_id,
        )


# Module-level singleton
connector_tool_provider = ConnectorToolProvider()
