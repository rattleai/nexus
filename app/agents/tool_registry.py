"""Dynamic tool registry for agent execution.

Manages the catalog of tools available to agents, combining:
    1. Built-in platform tools (from MCP server)
    2. Tenant-registered custom tools (external endpoints)
    3. Health checking and circuit breaking for external tools

Tools are resolved at execution time based on the agent's allowed_tools
list and the tenant's registered tools.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import TenantTool
from app.core.circuit_breaker import CircuitBreaker

logger = structlog.stdlib.get_logger()

# Circuit breaker for external tool calls
_tool_breaker = CircuitBreaker("tool", failure_threshold=3, recovery_timeout=60)


# Built-in tool definitions (from MCP server)
_BUILTIN_TOOLS: dict[str, dict[str, Any]] = {
    "ai_complete": {
        "description": "Run an AI completion using the platform's AI gateway",
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "messages": {"type": "array"},
                "max_tokens": {"type": "integer"},
            },
            "required": ["messages"],
        },
    },
    "ai_list_models": {
        "description": "List available AI models",
        "input_schema": {"type": "object", "properties": {}},
    },
    "file_upload": {
        "description": "Upload a file to storage",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["filename", "content"],
        },
    },
    "file_list": {
        "description": "List files in storage",
        "input_schema": {"type": "object", "properties": {}},
    },
    "job_create": {
        "description": "Create a background job",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_type": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["job_type"],
        },
    },
    "job_list": {
        "description": "List background jobs",
        "input_schema": {"type": "object", "properties": {}},
    },
    "webhook_create": {
        "description": "Create a webhook endpoint",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "events": {"type": "array"},
            },
            "required": ["url", "events"],
        },
    },
}


class ToolRegistry:
    """Manages tool discovery, resolution, and invocation for agents."""

    def list_builtin_tools(self) -> dict[str, dict[str, Any]]:
        """Return all built-in platform tools."""
        return _BUILTIN_TOOLS.copy()

    async def list_tenant_tools(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[TenantTool]:
        """List all active custom tools for a tenant."""
        stmt = select(TenantTool).where(
            TenantTool.tenant_id == tenant_id,
            TenantTool.is_active.is_(True),
            TenantTool.deleted_at.is_(None),
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def list_all_tools(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """List all available tools (built-in + tenant custom)."""
        tools = []

        # Built-in tools
        for name, info in _BUILTIN_TOOLS.items():
            tools.append({
                "name": name,
                "source": "builtin",
                "description": info["description"],
                "input_schema": info["input_schema"],
            })

        # Tenant tools
        tenant_tools = await self.list_tenant_tools(tenant_id, db)
        for tool in tenant_tools:
            tools.append({
                "name": tool.tool_name,
                "source": tool.source.value,
                "description": tool.description,
                "input_schema": tool.input_schema,
            })

        return tools

    async def invoke(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession | None = None,
    ) -> Any:
        """Invoke a tool by name with the given arguments.

        Routes to built-in handler or external endpoint based on tool type.
        """
        # Check built-in tools first
        if tool_name in _BUILTIN_TOOLS:
            return await self._invoke_builtin(tool_name, arguments, tenant_id)

        # Check tenant tools
        if db is None:
            return {"error": f"Tool '{tool_name}' not found (no db session for tenant tool lookup)"}

        stmt = select(TenantTool).where(
            TenantTool.tenant_id == tenant_id,
            TenantTool.tool_name == tool_name,
            TenantTool.is_active.is_(True),
            TenantTool.deleted_at.is_(None),
        )
        result = await db.execute(stmt)
        tenant_tool = result.scalar_one_or_none()

        if not tenant_tool:
            return {"error": f"Tool '{tool_name}' not found"}

        if not tenant_tool.endpoint_url:
            return {"error": f"Tool '{tool_name}' has no endpoint URL configured"}

        return await self._invoke_external(tenant_tool, arguments)

    async def _invoke_builtin(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> Any:
        """Invoke a built-in platform tool.

        In a full implementation, this would delegate to the actual MCP tool
        handlers. For now, returns a structured acknowledgment.
        """
        logger.info(
            "tool_invoke_builtin",
            tool_name=tool_name,
            tenant_id=str(tenant_id),
        )
        return {
            "tool": tool_name,
            "status": "executed",
            "arguments": arguments,
        }

    async def _invoke_external(
        self,
        tool: TenantTool,
        arguments: dict[str, Any],
    ) -> Any:
        """Invoke a tenant-registered external tool via HTTP."""
        breaker_key = CircuitBreaker.host_key(tool.endpoint_url)

        if _tool_breaker.is_open(breaker_key):
            return {"error": f"Tool '{tool.tool_name}' is temporarily unavailable (circuit open)"}

        try:
            headers = {"Content-Type": "application/json"}

            # Apply auth config if present
            auth_config = tool.auth_config or {}
            if auth_config.get("type") == "bearer":
                headers["Authorization"] = f"Bearer {auth_config.get('token', '')}"
            elif auth_config.get("type") == "api_key":
                header_name = auth_config.get("header", "X-API-Key")
                headers[header_name] = auth_config.get("key", "")

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    tool.endpoint_url,
                    json={"arguments": arguments},
                    headers=headers,
                )

            if response.status_code == 200:
                _tool_breaker.record_success(breaker_key)
                return response.json()
            else:
                _tool_breaker.record_failure(breaker_key)
                # Log the full response server-side but return only the status
                # code to the caller to avoid leaking external service details.
                logger.warning(
                    "tool_invoke_external_error",
                    tool_name=tool.tool_name,
                    status_code=response.status_code,
                    response_preview=response.text[:500],
                )
                return {
                    "error": f"Tool '{tool.tool_name}' returned status {response.status_code}",
                }

        except Exception as exc:
            _tool_breaker.record_failure(breaker_key)
            logger.warning(
                "tool_invoke_external_failed",
                tool_name=tool.tool_name,
                endpoint=tool.endpoint_url,
                error=str(exc),
            )
            return {"error": f"Tool '{tool.tool_name}' invocation failed"}

    async def health_check(
        self,
        tool: TenantTool,
    ) -> dict[str, Any]:
        """Check the health of an external tool."""
        if not tool.health_check_url:
            return {"status": "unknown", "reason": "no health check URL configured"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(tool.health_check_url)
            return {
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "status_code": response.status_code,
            }
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}


# Module-level singleton
tool_registry = ToolRegistry()
