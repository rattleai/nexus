"""Connector Executor: routes tool calls to the appropriate backend.

Handles MCP server invocation, OAuth API calls, and API key API calls with:

* **Circuit breaker** — per (tenant, connector) breaker prevents retry storms.
* **Rate limiting (P1.5)** — token bucket in Redis keyed (tenant, user, connector).
  Providers that return ``Retry-After`` trigger a backoff bucket blocking all
  users of that connector for the server-specified duration.
* **Credential injection** — always through ``CredentialManager.get_valid_token``
  which applies the distributed refresh lock.
* **Actor identity (P0.2)** — audit rows and rate-limit buckets key on the
  invoking user, not just the tenant, for confused-deputy prevention.
* **P0.6 api_config path** — HTTP API connectors read their base URL, method,
  path, and argument placement from ``ConnectorDefinition.api_config`` +
  tool_definitions, not from ``auth_config``.
* **Idempotency (P1.4)** — optional ``idempotency_key`` argument; downstream
  ``ConnectorAuditLog.request_summary`` records the key so duplicate calls
  are visible.
* **OTel GenAI semconv (P1.6)** — spans follow gen_ai.* + mcp.* conventions.
"""

from __future__ import annotations

import contextlib
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

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
from app.connectors.rate_limiter import (
    RateLimited,
    connector_rate_limiter,
)
from app.core.circuit_breaker import CircuitBreaker

logger = structlog.stdlib.get_logger()

_connector_breaker = CircuitBreaker(
    "connector",
    failure_threshold=3,
    recovery_timeout=60,
)

_PATH_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")


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
        actor_user_id: uuid.UUID | None = None,
        agent_instance_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """Invoke a tool through the appropriate connector backend."""
        breaker_key = f"{tenant_id}:{connector_def.slug}"

        if _connector_breaker.is_open(breaker_key):
            return {
                "error": (f"Connector '{connector_def.slug}' is temporarily unavailable (circuit open)"),
                "is_error": True,
            }

        try:
            await connector_rate_limiter.check_and_consume(
                tenant_id=tenant_id,
                connector_slug=connector_def.slug,
                actor_user_id=actor_user_id,
            )
        except RateLimited as exc:
            return {
                "error": "rate_limited",
                "retry_after_seconds": exc.retry_after,
                "is_error": True,
            }

        span = _start_tool_span(connector_def, tool_name)

        start_time = time.monotonic()
        result: Any = None
        error_msg: str | None = None
        status = "success"

        try:
            if connector_def.connector_type == ConnectorType.MCP_SERVER:
                result = await self._invoke_mcp(
                    connection,
                    connector_def,
                    tool_name,
                    arguments,
                )
            elif connector_def.connector_type in (
                ConnectorType.OAUTH_API,
                ConnectorType.API_KEY_API,
            ):
                result = await self._invoke_http(
                    connection,
                    connector_def,
                    tool_name,
                    arguments,
                    db,
                )
            else:
                return {
                    "error": f"Unsupported connector type: {connector_def.connector_type}",
                    "is_error": True,
                }

            _connector_breaker.record_success(breaker_key)
            connection.last_used_at = datetime.now(UTC)
            await db.flush()
            return result

        except CredentialError as exc:
            error_msg = str(exc)
            status = "failure"
            _connector_breaker.record_failure(breaker_key)
            return {
                "error": f"Authentication failed for '{connector_def.slug}': {error_msg}",
                "is_error": True,
            }

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
            return {
                "error": (f"Tool '{tool_name}' on '{connector_def.slug}' failed: {str(exc)[:200]}"),
                "is_error": True,
            }

        finally:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            _end_tool_span(span, status=status, latency_ms=latency_ms)

            try:
                audit = ConnectorAuditLog(
                    tenant_id=tenant_id,
                    connection_id=connection.id,
                    action="tool_invoke",
                    tool_name=tool_name,
                    status=status,
                    actor_type=actor_type,
                    actor_id=str(actor_user_id) if actor_user_id else None,
                    agent_instance_id=agent_instance_id,
                    latency_ms=latency_ms,
                    error_message=error_msg,
                    request_summary=({"idempotency_key": idempotency_key} if idempotency_key else None),
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
        """Invoke a tool via HTTP API with credential injection.

        Reads from ``connector_def.api_config`` (P0.6):
            api_base_url   — base URL, joined with tool's ``path``
            default_headers — merged into every request

        Reads from ``tool_definitions[*]``:
            method         — HTTP verb (GET/POST/PUT/PATCH/DELETE)
            path           — URL path template with {placeholder} support
            arg_location   — "query" | "json_body" | "path" | "mixed"
        """
        token = await credential_manager.get_valid_token(connection, connector_def, db)

        tool_defs = connector_def.tool_definitions or []
        tool_def = next((t for t in tool_defs if t.get("name") == tool_name), None)
        if not tool_def:
            return {
                "error": f"Tool '{tool_name}' not found in connector definition",
                "is_error": True,
            }

        api_config = connector_def.api_config or {}
        base_url = api_config.get("api_base_url", "")
        method = tool_def.get("method", "POST").upper()
        path_template = tool_def.get("path", "")
        arg_location = tool_def.get("arg_location", "json_body")

        if not base_url:
            return {
                "error": (f"Connector '{connector_def.slug}' has no api_base_url in api_config"),
                "is_error": True,
            }

        # Substitute path placeholders
        remaining_args = dict(arguments)
        path, path_args = _substitute_path(path_template, remaining_args)
        for k in path_args:
            remaining_args.pop(k, None)

        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}" if path else base_url

        from app.core.url_validation import validate_url

        validate_url(url)

        # Auth headers
        headers: dict[str, str] = {}
        default_headers = api_config.get("default_headers") or {}
        if isinstance(default_headers, dict):
            for k, v in default_headers.items():
                headers[str(k)] = str(v)

        auth_type = (
            connector_def.auth_type.value if hasattr(connector_def.auth_type, "value") else str(connector_def.auth_type)
        )
        if auth_type in ("oauth2", "bearer_token"):
            headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            header_name = api_config.get("api_key_header", "X-API-Key")
            headers[header_name] = token

        headers.setdefault("Content-Type", "application/json")

        timeout = httpx.Timeout(
            connect=5.0,
            read=float(settings.CONNECTOR_HTTP_REQUEST_TIMEOUT_SECONDS),
            write=10.0,
            pool=5.0,
        )

        query_params: dict[str, Any] | None = None
        json_body: dict[str, Any] | None = None

        if arg_location == "query":
            query_params = remaining_args
        elif arg_location == "json_body":
            json_body = remaining_args
        elif arg_location == "path":
            query_params = None
            json_body = None
        elif arg_location == "mixed":
            json_body = remaining_args
        else:
            json_body = remaining_args

        max_attempts = max(1, settings.CONNECTOR_DURABLE_MAX_ATTEMPTS)
        backoff = settings.CONNECTOR_DURABLE_RETRY_INITIAL_SECONDS

        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        params=query_params,
                        json=json_body if json_body is not None else None,
                    )
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_error = exc
                if attempt + 1 >= max_attempts:
                    break
                import asyncio

                await asyncio.sleep(backoff)
                backoff *= settings.CONNECTOR_DURABLE_RETRY_BACKOFF
                continue

            if response.status_code == 429:
                retry_after = _parse_retry_after(response)
                await connector_rate_limiter.apply_provider_backoff(
                    tenant_id=connection.tenant_id,
                    connector_slug=connector_def.slug,
                    retry_after=retry_after,
                )
                return {
                    "error": "rate_limited",
                    "retry_after_seconds": retry_after,
                    "is_error": True,
                }

            if response.status_code < 400:
                try:
                    return {"content": response.json(), "is_error": False}
                except Exception:
                    return {"content": response.text[:10000], "is_error": False}

            if 500 <= response.status_code < 600 and attempt + 1 < max_attempts:
                import asyncio

                await asyncio.sleep(backoff)
                backoff *= settings.CONNECTOR_DURABLE_RETRY_BACKOFF
                continue

            logger.warning(
                "connector_http_error",
                connector=connector_def.slug,
                tool=tool_name,
                status_code=response.status_code,
            )
            return {
                "error": f"API returned status {response.status_code}",
                "status_code": response.status_code,
                "is_error": True,
            }

        if last_error is not None:
            raise ConnectorExecutionError(str(last_error))
        return {"error": "Request failed with no response", "is_error": True}


connector_executor = ConnectorExecutor()


# ── Helpers ──────────────────────────────────────────────


def _substitute_path(
    path_template: str,
    arguments: dict[str, Any],
) -> tuple[str, set[str]]:
    """Substitute {placeholder} segments in the path template.

    Returns (path, set_of_keys_consumed). Values are URL-quoted.
    """
    consumed: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in arguments:
            consumed.add(key)
            return quote(str(arguments[key]), safe="")
        return match.group(0)

    path = _PATH_PLACEHOLDER_RE.sub(replace, path_template)
    return path, consumed


def _parse_retry_after(response: httpx.Response) -> int:
    """Parse the Retry-After header into seconds. Defaults to 60."""
    header = response.headers.get("Retry-After")
    if not header:
        return 60
    try:
        return max(1, int(header))
    except ValueError:
        return 60


def _start_tool_span(connector_def: ConnectorDefinition, tool_name: str) -> Any:
    """Start an OTel span with GenAI + MCP semconv attributes (P1.6)."""
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer(__name__)
        span_name = f"execute_tool {connector_def.slug}:{tool_name}"
        span = tracer.start_span(span_name)
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", tool_name)
        span.set_attribute("gen_ai.tool.type", "connector")
        span.set_attribute("mcp.connector.slug", connector_def.slug)
        span.set_attribute(
            "mcp.connector.type",
            connector_def.connector_type.value
            if hasattr(connector_def.connector_type, "value")
            else str(connector_def.connector_type),
        )
        span.set_attribute("mcp.trust_level", connector_def.trust_level.value)
        return span
    except Exception:
        return None


def _end_tool_span(span: Any, *, status: str, latency_ms: int) -> None:
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        span.set_attribute("gen_ai.tool.latency_ms", latency_ms)
        span.set_attribute("gen_ai.tool.status", status)
        span.set_status(Status(StatusCode.OK if status == "success" else StatusCode.ERROR))
    except Exception:
        pass
    with contextlib.suppress(Exception):
        span.end()
