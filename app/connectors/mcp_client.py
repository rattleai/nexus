"""MCP Client Pool: manages connections to external MCP servers.

Provides session pooling, tool/resource discovery, and tool invocation
for MCP server connectors. Uses the ``mcp`` Python SDK.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import structlog
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.stdio import StdioServerParameters, stdio_client

from app.config import settings
from app.connectors.models import ConnectorDefinition, TenantConnection

logger = structlog.stdlib.get_logger()


class MCPClientError(Exception):
    """Raised when MCP client operations fail."""


class MCPClientPool:
    """Manages pooled connections to external MCP servers.

    Sessions are keyed by ``(connector_definition_id, tenant_id)`` and
    lazily initialised on first use. Idle sessions are cleaned up by
    the periodic health-check Celery task.
    """

    def __init__(self) -> None:
        # Active sessions: (connector_def_id, tenant_id) → session context
        self._sessions: dict[tuple[uuid.UUID, uuid.UUID], _ManagedSession] = {}
        self._lock = asyncio.Lock()

    # ── Session Management ───────────────────────────────────

    @asynccontextmanager
    async def get_session(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ):
        """Get or create an MCP client session for a connection.

        Usage::

            async with pool.get_session(conn, cdef) as session:
                result = await session.call_tool("tool_name", {"arg": "val"})
        """
        key = (connector_def.id, connection.tenant_id)

        async with self._lock:
            managed = self._sessions.get(key)
            if managed and managed.is_alive:
                managed.last_used = time.monotonic()
                yield managed.session
                return

            # Clean up dead session if exists
            if managed:
                await self._close_session(key)

        # Create new session outside the lock
        managed = await self._create_session(connection, connector_def)

        async with self._lock:
            self._sessions[key] = managed

        try:
            yield managed.session
        except Exception:
            # On error, mark session for cleanup
            async with self._lock:
                if key in self._sessions:
                    self._sessions[key].is_alive = False
            raise

    async def _create_session(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> _ManagedSession:
        """Create a new MCP client session."""
        mcp_config = connector_def.mcp_config or {}
        transport = mcp_config.get("transport", "streamable_http")

        if transport == "streamable_http":
            return await self._create_http_session(connection, connector_def, mcp_config)
        elif transport == "stdio":
            return await self._create_stdio_session(connection, connector_def, mcp_config)
        else:
            raise MCPClientError(f"Unsupported MCP transport: {transport}")

    async def _create_http_session(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        mcp_config: dict[str, Any],
    ) -> _ManagedSession:
        """Create a Streamable HTTP MCP session."""
        server_url = mcp_config.get("server_url", "")
        if not server_url:
            raise MCPClientError(
                f"MCP server URL not configured for connector '{connector_def.slug}'"
            )

        # Validate URL to prevent SSRF
        from app.core.url_validation import validate_url
        validate_url(server_url)

        timeout = settings.CONNECTOR_MCP_CONNECT_TIMEOUT_SECONDS

        try:
            # Create the transport context managers
            # streamablehttp_client returns (read_stream, write_stream, get_url)
            ctx = streamablehttp_client(
                url=server_url,
                timeout=timeout,
            )
            streams = await ctx.__aenter__()
            read_stream, write_stream = streams[0], streams[1]

            # Create and initialise the session
            session = ClientSession(read_stream, write_stream)
            await session.initialize()

            logger.info(
                "mcp_session_created",
                connector=connector_def.slug,
                transport="streamable_http",
                server_url=server_url,
            )

            return _ManagedSession(
                session=session,
                transport_ctx=ctx,
                connector_slug=connector_def.slug,
            )

        except Exception as exc:
            logger.error(
                "mcp_session_create_failed",
                connector=connector_def.slug,
                transport="streamable_http",
                error=str(exc)[:200],
            )
            raise MCPClientError(
                f"Failed to connect to MCP server for '{connector_def.slug}': {exc}"
            ) from exc

    async def _create_stdio_session(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        mcp_config: dict[str, Any],
    ) -> _ManagedSession:
        """Create a stdio MCP session (local subprocess)."""
        command = mcp_config.get("command", "")
        args = mcp_config.get("args", [])
        env = mcp_config.get("env")

        if not command:
            raise MCPClientError(
                f"MCP command not configured for connector '{connector_def.slug}'"
            )

        try:
            server_params = StdioServerParameters(
                command=command,
                args=args,
                env=env,
            )
            ctx = stdio_client(server_params)
            streams = await ctx.__aenter__()
            read_stream, write_stream = streams[0], streams[1]

            session = ClientSession(read_stream, write_stream)
            await session.initialize()

            logger.info(
                "mcp_session_created",
                connector=connector_def.slug,
                transport="stdio",
                command=command,
            )

            return _ManagedSession(
                session=session,
                transport_ctx=ctx,
                connector_slug=connector_def.slug,
            )

        except Exception as exc:
            logger.error(
                "mcp_session_create_failed",
                connector=connector_def.slug,
                transport="stdio",
                error=str(exc)[:200],
            )
            raise MCPClientError(
                f"Failed to start MCP server for '{connector_def.slug}': {exc}"
            ) from exc

    async def _close_session(self, key: tuple[uuid.UUID, uuid.UUID]) -> None:
        """Close and remove a managed session."""
        managed = self._sessions.pop(key, None)
        if managed:
            try:
                if managed.transport_ctx:
                    await managed.transport_ctx.__aexit__(None, None, None)
            except Exception:
                logger.debug("mcp_session_close_error", exc_info=True)

    # ── Tool Discovery ───────────────────────────────────────

    async def discover_tools(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> list[dict[str, Any]]:
        """Discover available tools from an MCP server.

        Returns a list of tool schema dicts (name, description, inputSchema).
        Caches the result on the TenantConnection model.
        """
        async with self.get_session(connection, connector_def) as session:
            result = await session.list_tools()

        tools = []
        for tool in result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
            })

        logger.info(
            "mcp_tools_discovered",
            connector=connector_def.slug,
            tool_count=len(tools),
        )
        return tools

    async def discover_resources(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> list[dict[str, Any]]:
        """Discover available resources from an MCP server."""
        async with self.get_session(connection, connector_def) as session:
            result = await session.list_resources()

        resources = []
        for resource in result.resources:
            resources.append({
                "uri": str(resource.uri),
                "name": resource.name or "",
                "description": resource.description or "",
                "mimeType": resource.mimeType if hasattr(resource, "mimeType") else None,
            })
        return resources

    # ── Tool Invocation ──────────────────────────────────────

    async def invoke_tool(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Invoke a tool on an MCP server.

        Returns the tool result content, truncated to max output size.
        """
        async with self.get_session(connection, connector_def) as session:
            result = await session.call_tool(tool_name, arguments)

        # Normalise MCP result to a serialisable format
        if result.content:
            # MCP returns a list of content blocks (text, image, resource)
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif hasattr(block, "data"):
                    parts.append(f"[binary: {getattr(block, 'mimeType', 'unknown')}]")
                else:
                    parts.append(str(block))

            output = "\n".join(parts)

            # Enforce output size limit
            max_bytes = settings.CONNECTOR_MAX_TOOL_OUTPUT_BYTES
            if len(output.encode()) > max_bytes:
                output = output[:max_bytes] + "\n... (truncated)"

            return {"content": output, "is_error": result.isError if hasattr(result, "isError") else False}

        return {"content": "", "is_error": False}

    # ── Resource Reading ─────────────────────────────────────

    async def read_resource(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        resource_uri: str,
    ) -> dict[str, Any]:
        """Read a resource from an MCP server."""
        async with self.get_session(connection, connector_def) as session:
            result = await session.read_resource(resource_uri)

        contents = []
        for item in result.contents:
            if hasattr(item, "text"):
                contents.append({"type": "text", "text": item.text})
            elif hasattr(item, "blob"):
                contents.append({"type": "blob", "mimeType": getattr(item, "mimeType", "")})
        return {"contents": contents}

    # ── Lifecycle ────────────────────────────────────────────

    async def close_connection(
        self,
        connector_def_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        """Close the session for a specific connection."""
        key = (connector_def_id, tenant_id)
        async with self._lock:
            await self._close_session(key)

    async def cleanup_idle(self, max_idle_seconds: int | None = None) -> int:
        """Close sessions that have been idle beyond the timeout.

        Returns the number of sessions closed.
        """
        max_idle = max_idle_seconds or settings.CONNECTOR_MCP_IDLE_TIMEOUT_SECONDS
        now = time.monotonic()
        to_close: list[tuple[uuid.UUID, uuid.UUID]] = []

        async with self._lock:
            for key, managed in self._sessions.items():
                if now - managed.last_used > max_idle:
                    to_close.append(key)

            for key in to_close:
                await self._close_session(key)

        if to_close:
            logger.info("mcp_idle_sessions_closed", count=len(to_close))
        return len(to_close)

    async def shutdown(self) -> None:
        """Close all active sessions."""
        async with self._lock:
            keys = list(self._sessions.keys())
            for key in keys:
                await self._close_session(key)
        logger.info("mcp_client_pool_shutdown")


class _ManagedSession:
    """Wraps a ClientSession with lifecycle metadata."""

    __slots__ = ("session", "transport_ctx", "connector_slug", "created_at", "last_used", "is_alive")

    def __init__(
        self,
        session: ClientSession,
        transport_ctx: Any,
        connector_slug: str,
    ) -> None:
        self.session = session
        self.transport_ctx = transport_ctx
        self.connector_slug = connector_slug
        self.created_at = time.monotonic()
        self.last_used = time.monotonic()
        self.is_alive = True


# Module-level singleton
mcp_client_pool = MCPClientPool()
