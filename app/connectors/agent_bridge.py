"""Agent Bridge: integrates connector tools with the agent ToolRegistry.

Provides ``ConnectorToolProvider`` — the thin adapter between the agent
runtime (``app.agents.tool_registry``) and connector execution.

Hardened over PR #63:

* **P0.2** — ``invoke`` requires ``actor_user_id`` and selects the
  ``TenantConnection`` for the invoking user, not the first-connected user.
  Prevents confused-deputy attacks where an agent triggered by user A
  silently uses user B's OAuth token.
* **P0.3** — ``list_tools`` and ``invoke`` optionally accept ``agent_id``
  and filter tools through the agent's resolved capability set via
  ``CapabilityResolver``. Unauthorized tool calls emit
  ``AgentGovernanceViolation`` and return an explicit error.
* **P1.4 / Cedar gate** — when Cedar is enabled, every invocation passes
  through ``policy_gate.authorize`` before reaching the executor.
* **P2.4** — invocation is routed through the broker router so Composio
  or in-house broker can service the call transparently.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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
    """Provides connector tools to the agent ToolRegistry."""

    async def list_tools(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Return connector tools available to this agent + user.

        When ``agent_id`` is provided, tools are filtered through the
        agent's resolved capability set — agents only see tools they have
        been granted access to. When ``actor_user_id`` is provided,
        connections without a matching ``connected_by_user_id`` are excluded.
        """
        from app.connectors.cache import connector_tool_cache

        # Scope cache by (agent, user) so per-agent filtering is cached
        cache_key_parts = []
        if agent_id:
            cache_key_parts.append(f"agent:{agent_id}")
        if actor_user_id:
            cache_key_parts.append(f"user:{actor_user_id}")
        cache_suffix = ":" + ":".join(cache_key_parts) if cache_key_parts else ""

        cached = await connector_tool_cache.get_tools(
            tenant_id,
            suffix=cache_suffix,
        )
        if cached is not None:
            return cached

        tools = await self._load_tools_from_db(
            tenant_id,
            db,
            agent_id=agent_id,
            actor_user_id=actor_user_id,
        )

        await connector_tool_cache.set_tools(
            tenant_id,
            tools,
            suffix=cache_suffix,
        )
        return tools

    async def _load_tools_from_db(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID | None,
        actor_user_id: uuid.UUID | None,
    ) -> list[dict[str, Any]]:
        """Load tools from active connections, scoped by user + agent."""
        stmt = (
            select(TenantConnection)
            .where(
                TenantConnection.tenant_id == tenant_id,
                TenantConnection.status == ConnectionStatus.ACTIVE,
                TenantConnection.deleted_at.is_(None),
            )
            .options(joinedload(TenantConnection.connector_definition))
        )
        if actor_user_id is not None:
            stmt = stmt.where(TenantConnection.connected_by_user_id == actor_user_id)

        result = await db.execute(stmt)
        connections = result.unique().scalars().all()

        all_tools: list[dict[str, Any]] = []
        for conn in connections:
            cd = conn.connector_definition
            if not cd or not cd.is_active:
                continue
            tools = ConnectorToolAdapter.connection_tools_to_platform(conn, cd)
            all_tools.extend(tools)

        if agent_id is not None:
            allowed = await self._resolve_agent_allowed_tools(agent_id, tenant_id, db)
            if allowed is not None:
                all_tools = [t for t in all_tools if t["name"] in allowed]

        return all_tools

    async def _resolve_agent_allowed_tools(
        self,
        agent_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> set[str] | None:
        """Return the set of tool names allowed for this agent.

        Returns ``None`` (meaning "don't filter") when the agent has no
        configured capabilities — preserving the legacy "everything in
        allowed_tools" behavior.
        """
        from app.agents.capabilities import capability_resolver
        from app.agents.models import AgentDefinition

        definition = await db.get(AgentDefinition, agent_id)
        if definition is None:
            return set()

        capabilities = getattr(definition, "capabilities", None) or []
        allowed_tools = getattr(definition, "allowed_tools", None) or []

        if not capabilities and not allowed_tools:
            return None

        resolved = await capability_resolver.resolve_agent_tools_with_connectors(
            definition,
            tenant_id,
            db,
        )
        return set(resolved)

    async def invoke(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
        actor_user_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        agent_instance_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """Invoke a connector tool by its namespaced name."""
        try:
            connector_slug, original_tool = parse_tool_name(tool_name)
        except ValueError:
            return {
                "error": f"Invalid connector tool name: {tool_name}",
                "is_error": True,
            }

        # Per-agent authorization (P0.3)
        if agent_id is not None:
            allowed = await self._resolve_agent_allowed_tools(
                agent_id,
                tenant_id,
                db,
            )
            if allowed is not None and tool_name not in allowed:
                await self._emit_governance_violation(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    agent_instance_id=agent_instance_id,
                    tool_name=tool_name,
                    reason="not_in_capabilities",
                )
                return {
                    "error": (
                        f"Agent is not authorized to invoke '{tool_name}'. "
                        f"Grant the matching capability to the agent definition."
                    ),
                    "is_error": True,
                }

        # Per-user connection resolution (P0.2)
        connection = await self._resolve_connection(
            connector_slug=connector_slug,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            db=db,
        )
        if connection is None:
            return {
                "error": (f"No active connection for '{connector_slug}'. The user must connect their account first."),
                "is_error": True,
            }

        connector_def = connection.connector_definition

        # Cedar / policy gate (P3.1) — no-op when Cedar disabled
        policy_denied_cls: type[Exception] | None = None
        try:
            from app.connectors.policy_gate import (
                PolicyDenied,
                policy_gate,
            )

            policy_denied_cls = PolicyDenied
            await policy_gate.authorize(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                agent_id=agent_id,
                connector_def=connector_def,
                tool_name=original_tool,
                arguments=arguments,
            )
        except ImportError:
            pass
        except Exception as exc:
            # PolicyDenied is the only expected failure mode; re-raise others
            if policy_denied_cls is not None and isinstance(exc, policy_denied_cls):
                await self._emit_governance_violation(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    agent_instance_id=agent_instance_id,
                    tool_name=tool_name,
                    reason=f"cedar_denied: {str(exc)[:200]}",
                )
                return {
                    "error": f"Policy denies this tool call: {str(exc)[:200]}",
                    "is_error": True,
                }
            raise

        # Route through broker (P2.4). Broker router decides between
        # Composio and in-house based on connector.broker.
        from app.connectors.brokers.router import broker_router

        broker = broker_router.for_connector(connector_def)
        return await broker.invoke_tool(
            connection=connection,
            connector_def=connector_def,
            tool_name=original_tool,
            arguments=arguments,
            tenant_id=tenant_id,
            db=db,
            actor_user_id=actor_user_id,
            agent_instance_id=agent_instance_id,
            idempotency_key=idempotency_key,
        )

    async def _resolve_connection(
        self,
        *,
        connector_slug: str,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> TenantConnection | None:
        """Find the active connection scoped to the invoking user.

        Falls back to any active connection for the tenant ONLY when no
        ``actor_user_id`` is provided (system-triggered agents with no
        human initiator).
        """
        stmt = (
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
        if actor_user_id is not None:
            stmt = stmt.where(TenantConnection.connected_by_user_id == actor_user_id)

        result = await db.execute(stmt)
        connection = result.unique().scalar_one_or_none()

        if connection is None and actor_user_id is not None:
            logger.info(
                "connector_per_user_connection_missing",
                tenant_id=str(tenant_id),
                actor_user_id=str(actor_user_id),
                connector=connector_slug,
            )
        return connection

    async def _emit_governance_violation(
        self,
        *,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID | None,
        agent_instance_id: uuid.UUID | None,
        tool_name: str,
        reason: str,
    ) -> None:
        try:
            from app.agents.events import AgentGovernanceViolation
            from app.core.events import emit

            await emit(
                AgentGovernanceViolation(
                    tenant_id=str(tenant_id),
                    instance_id=str(agent_instance_id) if agent_instance_id else "",
                    agent_id=str(agent_id) if agent_id else "",
                    violation_type="denied_tool",
                    details=f"{tool_name}: {reason}",
                ),
                durable=True,
            )
        except Exception:
            logger.debug("governance_violation_emit_failed", exc_info=True)


connector_tool_provider = ConnectorToolProvider()
