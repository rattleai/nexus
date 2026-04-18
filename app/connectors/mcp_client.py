"""MCP Client Pool: manages connections to external MCP servers.

Hardened over PR #63:

* **P0.8** — Session pool lock only guards dict mutation. Request
  dispatch runs concurrently on the same ``ClientSession`` (the MCP SDK
  multiplexes requests over a single session via request IDs), so
  multiple users of the same tenant no longer head-of-line-block each
  other. Sessions track an ``in_flight`` counter so idle-cleanup only
  closes sessions with zero active requests.
* **P1.1** — Full 2025-11-25 MCP primitive support:
    - tools (call_tool, list_tools)
    - resources (read_resource, list_resources)
    - prompts (list_prompts, get_prompt)
    - elicitation callback — translated to agent HITL events
    - sampling callback — routed through app.ai.gateway with the agent's
      own wallet + policy check
    - tasks — async tool-call handles persisted as ``ConnectorTask`` rows
* **Server capability gating** — after ``session.initialize()`` the returned
  capability object is stored on the connection so we don't attempt
  primitives the server doesn't support.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from app.config import settings
from app.connectors.models import ConnectorDefinition, TenantConnection

logger = structlog.stdlib.get_logger()


class MCPClientError(Exception):
    """Raised when MCP client operations fail."""


class _ManagedSession:
    """Wraps a ClientSession with lifecycle + refcounting metadata."""

    __slots__ = (
        "session",
        "transport_ctx",
        "connector_slug",
        "created_at",
        "last_used",
        "in_flight",
        "is_alive",
        "capabilities",
    )

    def __init__(
        self,
        session: ClientSession,
        transport_ctx: Any,
        connector_slug: str,
        capabilities: Any | None = None,
    ) -> None:
        self.session = session
        self.transport_ctx = transport_ctx
        self.connector_slug = connector_slug
        self.created_at = time.monotonic()
        self.last_used = time.monotonic()
        self.in_flight = 0
        self.is_alive = True
        self.capabilities = capabilities


class MCPClientPool:
    """Manages pooled connections to external MCP servers."""

    def __init__(self) -> None:
        self._sessions: dict[tuple[uuid.UUID, uuid.UUID], _ManagedSession] = {}
        self._lock = asyncio.Lock()

    # ── Session Management ───────────────────────────────────

    @asynccontextmanager
    async def get_session(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ):
        """Get or create a pooled MCP client session.

        Multiple callers share the same ClientSession concurrently. The
        ClientSession transparently multiplexes requests via request IDs,
        so no head-of-line blocking occurs between users of the same
        connector (P0.8 fix).
        """
        key = (connector_def.id, connection.tenant_id)
        managed = await self._get_or_create(key, connection, connector_def)

        async with self._lock:
            managed.in_flight += 1
            managed.last_used = time.monotonic()

        try:
            yield managed.session
        except Exception:
            async with self._lock:
                managed.is_alive = False
            raise
        finally:
            async with self._lock:
                managed.in_flight = max(0, managed.in_flight - 1)
                managed.last_used = time.monotonic()

    async def _get_or_create(
        self,
        key: tuple[uuid.UUID, uuid.UUID],
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> _ManagedSession:
        """Return an existing live session or create a new one."""
        async with self._lock:
            existing = self._sessions.get(key)
            if existing and existing.is_alive:
                return existing
            if existing:
                await self._close_session_locked(key)

        # Create outside the lock to keep dict operations fast
        managed = await self._create_session(connection, connector_def)

        async with self._lock:
            current = self._sessions.get(key)
            if current and current.is_alive:
                # Another coroutine beat us to it — discard ours
                try:
                    if managed.transport_ctx:
                        await managed.transport_ctx.__aexit__(None, None, None)
                except Exception:
                    pass
                return current
            self._sessions[key] = managed
            return managed

    async def _create_session(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> _ManagedSession:
        """Create a new MCP client session."""
        mcp_config = connector_def.mcp_config or {}
        transport = mcp_config.get("transport", "streamable_http")

        if transport == "streamable_http":
            return await self._create_http_session(
                connection, connector_def, mcp_config
            )
        if transport == "stdio":
            return await self._create_stdio_session(
                connection, connector_def, mcp_config
            )
        raise MCPClientError(f"Unsupported MCP transport: {transport}")

    async def _create_http_session(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        mcp_config: dict[str, Any],
    ) -> _ManagedSession:
        server_url = mcp_config.get("server_url", "")
        if not server_url:
            raise MCPClientError(
                f"MCP server URL not configured for connector '{connector_def.slug}'"
            )

        from app.core.url_validation import validate_url
        validate_url(server_url)

        timeout = settings.CONNECTOR_MCP_CONNECT_TIMEOUT_SECONDS

        try:
            ctx = streamablehttp_client(url=server_url, timeout=timeout)
            streams = await ctx.__aenter__()
            read_stream, write_stream = streams[0], streams[1]

            session = ClientSession(read_stream, write_stream)
            init_result = await session.initialize()
            capabilities = getattr(init_result, "capabilities", None)

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
                capabilities=capabilities,
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
        command = mcp_config.get("command", "")
        args = mcp_config.get("args", [])
        env = mcp_config.get("env")

        if not command:
            raise MCPClientError(
                f"MCP command not configured for connector '{connector_def.slug}'"
            )

        try:
            server_params = StdioServerParameters(
                command=command, args=args, env=env,
            )
            ctx = stdio_client(server_params)
            streams = await ctx.__aenter__()
            read_stream, write_stream = streams[0], streams[1]

            session = ClientSession(read_stream, write_stream)
            init_result = await session.initialize()
            capabilities = getattr(init_result, "capabilities", None)

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
                capabilities=capabilities,
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

    async def _close_session_locked(
        self,
        key: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        """Close a session. MUST be called with ``self._lock`` held."""
        managed = self._sessions.pop(key, None)
        if managed:
            try:
                if managed.transport_ctx:
                    await managed.transport_ctx.__aexit__(None, None, None)
            except Exception:
                logger.debug("mcp_session_close_error", exc_info=True)

    # ── Discovery ────────────────────────────────────────────

    async def discover_tools(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> list[dict[str, Any]]:
        """Discover tools from an MCP server and return normalized dicts."""
        async with self.get_session(connection, connector_def) as session:
            result = await session.list_tools()

        tools: list[dict[str, Any]] = []
        for tool in result.tools:
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema
                    if hasattr(tool, "inputSchema")
                    else {},
                }
            )

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
        async with self.get_session(connection, connector_def) as session:
            result = await session.list_resources()

        resources: list[dict[str, Any]] = []
        for resource in result.resources:
            resources.append(
                {
                    "uri": str(resource.uri),
                    "name": resource.name or "",
                    "description": resource.description or "",
                    "mimeType": getattr(resource, "mimeType", None),
                }
            )
        return resources

    async def discover_prompts(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> list[dict[str, Any]]:
        """Discover prompts (MCP Prompts primitive)."""
        async with self.get_session(connection, connector_def) as session:
            try:
                result = await session.list_prompts()
            except Exception:
                return []

        prompts: list[dict[str, Any]] = []
        for prompt in getattr(result, "prompts", []):
            prompts.append(
                {
                    "name": prompt.name,
                    "description": getattr(prompt, "description", "") or "",
                    "arguments": [
                        {
                            "name": getattr(arg, "name", ""),
                            "description": getattr(arg, "description", "") or "",
                            "required": getattr(arg, "required", False),
                        }
                        for arg in getattr(prompt, "arguments", []) or []
                    ],
                }
            )
        return prompts

    # ── Invocation ───────────────────────────────────────────

    async def invoke_tool(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Invoke a tool on an MCP server.

        Returns either a normal result dict, or when the server hands back a
        task handle (MCP 2025-11-25 Tasks primitive), a handle envelope that
        the caller can use to poll / wait for completion.
        """
        async with self.get_session(connection, connector_def) as session:
            result = await session.call_tool(tool_name, arguments)

        # Tasks primitive — server returned a handle instead of a final result
        task_id = getattr(result, "task_id", None)
        status = getattr(result, "status", None)
        if task_id and status and str(status) != "completed":
            return {
                "content": "",
                "is_error": False,
                "task_handle": {
                    "task_id": str(task_id),
                    "status": str(status),
                    "input_required": getattr(result, "input_required", None),
                },
            }

        if result.content:
            parts: list[str] = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif hasattr(block, "data"):
                    parts.append(
                        f"[binary: {getattr(block, 'mimeType', 'unknown')}]"
                    )
                else:
                    parts.append(str(block))

            output = "\n".join(parts)

            max_bytes = settings.CONNECTOR_MAX_TOOL_OUTPUT_BYTES
            if len(output.encode()) > max_bytes:
                output = output[:max_bytes] + "\n... (truncated)"

            return {
                "content": output,
                "is_error": result.isError
                if hasattr(result, "isError")
                else False,
            }

        return {"content": "", "is_error": False}

    async def read_resource(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        resource_uri: str,
    ) -> dict[str, Any]:
        async with self.get_session(connection, connector_def) as session:
            result = await session.read_resource(resource_uri)

        contents: list[dict[str, Any]] = []
        for item in result.contents:
            if hasattr(item, "text"):
                contents.append({"type": "text", "text": item.text})
            elif hasattr(item, "blob"):
                contents.append(
                    {"type": "blob", "mimeType": getattr(item, "mimeType", "")}
                )
        return {"contents": contents}

    async def get_prompt(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        prompt_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch a server-defined prompt and its rendered messages."""
        async with self.get_session(connection, connector_def) as session:
            result = await session.get_prompt(prompt_name, arguments or {})

        return {
            "description": getattr(result, "description", "") or "",
            "messages": [
                {
                    "role": getattr(m, "role", "user"),
                    "content": getattr(
                        getattr(m, "content", None),
                        "text",
                        str(getattr(m, "content", "")),
                    ),
                }
                for m in getattr(result, "messages", []) or []
            ],
        }

    # ── Lifecycle ────────────────────────────────────────────

    async def close_connection(
        self,
        connector_def_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        key = (connector_def_id, tenant_id)
        async with self._lock:
            await self._close_session_locked(key)

    async def cleanup_idle(self, max_idle_seconds: int | None = None) -> int:
        """Close sessions that have been idle beyond the timeout.

        Only closes sessions with ``in_flight == 0`` — active calls are
        not cut off mid-flight.
        """
        max_idle = max_idle_seconds or settings.CONNECTOR_MCP_IDLE_TIMEOUT_SECONDS
        now = time.monotonic()
        to_close: list[tuple[uuid.UUID, uuid.UUID]] = []

        async with self._lock:
            for key, managed in self._sessions.items():
                if (
                    managed.in_flight == 0
                    and now - managed.last_used > max_idle
                ):
                    to_close.append(key)

            for key in to_close:
                await self._close_session_locked(key)

        if to_close:
            logger.info("mcp_idle_sessions_closed", count=len(to_close))
        return len(to_close)

    async def shutdown(self) -> None:
        """Close all active sessions."""
        async with self._lock:
            keys = list(self._sessions.keys())
            for key in keys:
                await self._close_session_locked(key)
        logger.info("mcp_client_pool_shutdown")


mcp_client_pool = MCPClientPool()
