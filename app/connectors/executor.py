"""Connector Executor: routes tool calls to the appropriate backend.

Handles MCP server invocation, OAuth API calls, and API key API calls
with circuit breaking, retry, and credential injection.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.credentials import CredentialError, credential_manager
from app.connectors.models import (
    ConnectorAuditLog,
    ConnectorDefinition,
    ConnectorType,
    TenantConnection,
)
from app.core.circuit_breaker import CircuitBreaker

logger = structlog.stdlib.get_logger()

# Per-connector circuit breaker
_connector_breaker = CircuitBreaker("connector", failure_threshold=3, recovery_timeout=60)


class ConnectorExecutionError(Exception):
    """Raised when a connector tool invocation fails."""


class ConnectorExecutor:
    """Routes tool calls to the appropriate connector backend."""

    async def invoke(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
        actor_type: str = "agent",
        actor_id: str | None = None,
        agent_instance_id: uuid.UUID | None = None,
    ) -> Any:
        """Invoke a tool through the appropriate connector backend.

        Routes to MCP client, OAuth API, or API key API based on
        the connector's type. Handles credential injection, circuit
        breaking, and audit logging.
        """
        breaker_key = f"{tenant_id}:{connector_def.slug}"

        if _connector_breaker.is_open(breaker_key):
            return {
                "error": f"Connector '{connector_def.slug}' is temporarily unavailable (circuit open)",
            }

        start_time = time.monotonic()
        result = None
        error_msg = None
        status = "success"

        try:
            if connector_def.connector_type == ConnectorType.MCP_SERVER:
                result = await self._invoke_mcp(
                    connection, connector_def, tool_name, arguments,
                )
            elif connector_def.connector_type in (
                ConnectorType.OAUTH_API,
                ConnectorType.API_KEY_API,
            ):
                result = await self._invoke_http(
                    connection, connector_def, tool_name, arguments, db,
                )
            else:
                return {"error": f"Unsupported connector type: {connector_def.connector_type}"}

            _connector_breaker.record_success(breaker_key)

            # Update last_used_at
            connection.last_used_at = datetime.now(UTC)
            await db.flush()

            return result

        except CredentialError as exc:
            error_msg = str(exc)
            status = "failure"
            _connector_breaker.record_failure(breaker_key)
            return {"error": f"Authentication failed for '{connector_def.slug}': {error_msg}"}

        except Exception as exc:
            error_msg = str(exc)[:500]
            status = "failure"
            _connector_breaker.record_failure(breaker_key)
            logger.warning(
                "connector_invoke_failed",
                connector=connector_def.slug,
                tool=tool_name,
                error=error_msg,
            )
            return {"error": f"Tool '{tool_name}' on '{connector_def.slug}' failed: {str(exc)[:200]}"}

        finally:
            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Audit log (best-effort, non-blocking)
            try:
                audit = ConnectorAuditLog(
                    tenant_id=tenant_id,
                    connection_id=connection.id,
                    action="tool_invoke",
                    tool_name=tool_name,
                    status=status,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    agent_instance_id=agent_instance_id,
                    latency_ms=latency_ms,
                    error_message=error_msg,
                )
                db.add(audit)
                await db.flush()
            except Exception:
                logger.debug("connector_audit_log_failed", exc_info=True)

    async def _invoke_mcp(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Invoke a tool via the MCP client pool."""
        from app.connectors.mcp_client import mcp_client_pool

        return await mcp_client_pool.invoke_tool(
            connection=connection,
            connector_def=connector_def,
            tool_name=tool_name,
            arguments=arguments,
        )

    async def _invoke_http(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tool_name: str,
        arguments: dict[str, Any],
        db: AsyncSession,
    ) -> Any:
        """Invoke a tool via HTTP API with credential injection."""
        # Get valid token
        token = await credential_manager.get_valid_token(connection, connector_def, db)

        # Find the tool definition
        tool_defs = connector_def.tool_definitions or []
        tool_def = next((t for t in tool_defs if t.get("name") == tool_name), None)
        if not tool_def:
            return {"error": f"Tool '{tool_name}' not found in connector definition"}

        # Build the request
        api_config = connector_def.auth_config or {}
        base_url = api_config.get("api_base_url", "")
        method = tool_def.get("method", "POST").upper()
        path = tool_def.get("path", "")

        if not base_url and not path:
            return {"error": f"No API endpoint configured for tool '{tool_name}'"}

        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}" if base_url else path

        # SSRF validation
        from app.core.url_validation import validate_url
        validate_url(url)

        # Build headers based on auth type
        headers: dict[str, str] = {"Content-Type": "application/json"}
        auth_type = connector_def.auth_type

        if auth_type in ("oauth2", "bearer_token"):
            headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            header_name = api_config.get("api_key_header", "X-API-Key")
            headers[header_name] = token

        # Execute the request
        timeout = httpx.Timeout(
            connect=5.0,
            read=float(settings.CONNECTOR_MCP_REQUEST_TIMEOUT_SECONDS),
            write=10.0,
            pool=5.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=arguments)
            elif method == "POST":
                response = await client.post(url, headers=headers, json=arguments)
            elif method == "PUT":
                response = await client.put(url, headers=headers, json=arguments)
            elif method == "PATCH":
                response = await client.patch(url, headers=headers, json=arguments)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                return {"error": f"Unsupported HTTP method: {method}"}

        if response.status_code < 400:
            try:
                return {"content": response.json(), "is_error": False}
            except Exception:
                return {"content": response.text[:10000], "is_error": False}
        else:
            logger.warning(
                "connector_http_error",
                connector=connector_def.slug,
                tool=tool_name,
                status_code=response.status_code,
            )
            return {
                "error": f"API returned status {response.status_code}",
                "is_error": True,
            }


# Module-level singleton
connector_executor = ConnectorExecutor()
