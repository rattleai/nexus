"""Dynamic tool registry for agent execution.

Manages the catalog of tools available to agents, combining:
    1. Built-in platform tools (from MCP server)
    2. Tenant-registered custom tools (external endpoints)
    3. Health checking and circuit breaking for external tools
    4. Supply chain verification (schema drift, signature, behavioral monitoring)

Tools are resolved at execution time based on the agent's allowed_tools
list and the tenant's registered tools.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import TenantTool
from app.config import settings
from app.core.circuit_breaker import CircuitBreaker
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Circuit breaker for external tool calls
_tool_breaker = CircuitBreaker("tool", failure_threshold=3, recovery_timeout=60)

# Redis key for tool behavioral monitoring
_TOOL_BEHAVIOR_KEY = "agent:tool:behavior:{tenant_id}:{tool_name}"


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
    "code_execute": {
        "description": "Execute Python code in a secure sandbox with resource limits. "
        "Use this to perform calculations, data processing, or run algorithms. "
        "The sandbox blocks network access, filesystem writes, and dangerous imports.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Set a 'result' variable for structured output.",
                },
                "input_data": {
                    "type": "object",
                    "description": "JSON data accessible as 'input_data' variable in the code.",
                },
            },
            "required": ["code"],
        },
    },
    "rag_search": {
        "description": (
            "Search documents and agent memory using AI-powered hybrid search. "
            "Combines vector similarity (semantic meaning) with full-text keyword matching. "
            "Use this to find relevant information across uploaded documents, JSON data, "
            "PDFs, spreadsheets, and agent memory. Supports filtering by source type, "
            "date range, and tags."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query (e.g., 'stainless steel bolts with high tensile strength')",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["chunks", "memory"]},
                    "description": "Where to search: 'chunks' (documents), 'memory' (agent memory), or both. Defaults to both.",
                },
                "search_type": {
                    "type": "string",
                    "enum": ["hybrid", "vector", "text"],
                    "description": "Search mode: 'hybrid' (recommended, combines vector+text), 'vector' (semantic only), 'text' (keyword only). Defaults to hybrid.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (1-50). Defaults to 10.",
                },
                "source_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by document type (e.g., ['json', 'pdf', 'csv']). Optional.",
                },
                "rerank": {
                    "type": "boolean",
                    "description": "Apply re-ranking for improved precision. Defaults to false.",
                },
            },
            "required": ["query"],
        },
    },
}


import contextlib

from app.plugins.base import CapabilityDomain, ToolCapability

PLATFORM_CAPABILITIES = CapabilityDomain(
    slug="platform",
    label="Platform",
    icon="Cpu",
    capabilities=(
        ToolCapability(
            slug="platform:ai",
            label="AI Completion",
            description="Run AI completions and list available models",
            tools=("ai_complete", "ai_list_models"),
        ),
        ToolCapability(
            slug="platform:search",
            label="RAG Search",
            description="Search documents and memory using AI-powered hybrid vector + text search",
            tools=("rag_search",),
        ),
        ToolCapability(
            slug="platform:files",
            label="File Management",
            description="Upload and list files in storage",
            tools=("file_upload", "file_list"),
        ),
        ToolCapability(
            slug="platform:jobs",
            label="Background Jobs",
            description="Create and list background jobs",
            tools=("job_create", "job_list"),
            risk_level="medium",
        ),
        ToolCapability(
            slug="platform:webhooks",
            label="Webhooks",
            description="Create webhook endpoints for event notifications",
            tools=("webhook_create",),
            risk_level="medium",
        ),
        ToolCapability(
            slug="platform:code",
            label="Code Execution",
            description="Execute Python code in a secure sandbox",
            tools=("code_execute",),
            risk_level="high",
        ),
    ),
)


def _get_all_builtin_tools() -> dict[str, dict[str, Any]]:
    """Return infra tools merged with plugin-contributed tool definitions."""
    all_tools = _BUILTIN_TOOLS.copy()
    from app.plugins.registry import registry as _plugin_registry

    for _plugin in _plugin_registry:
        all_tools.update(_plugin.get_agent_tool_definitions())
    return all_tools


class ToolRegistry:
    """Manages tool discovery, resolution, and invocation for agents."""

    def list_builtin_tools(self) -> dict[str, dict[str, Any]]:
        """Return all built-in platform tools (infra + plugins)."""
        return _get_all_builtin_tools()

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
        *,
        agent_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """List all available tools (built-in + tenant custom + connectors).

        When ``agent_id`` / ``actor_user_id`` are supplied, connector tools
        are filtered to what this agent + user is authorized to call.
        """
        tools = []

        # Built-in tools (infra + plugins)
        all_builtin = _get_all_builtin_tools()
        for name, info in all_builtin.items():
            tools.append(
                {
                    "name": name,
                    "source": "builtin",
                    "description": info["description"],
                    "input_schema": info["input_schema"],
                }
            )

        # Tenant tools
        tenant_tools = await self.list_tenant_tools(tenant_id, db)
        for tool in tenant_tools:
            tools.append(
                {
                    "name": tool.tool_name,
                    "source": tool.source.value,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
            )

        # Connector tools (from active connections)
        if settings.CONNECTOR_ENABLED:
            try:
                from app.connectors.agent_bridge import connector_tool_provider

                connector_tools = await connector_tool_provider.list_tools(
                    tenant_id,
                    db,
                    agent_id=agent_id,
                    actor_user_id=actor_user_id,
                )
                tools.extend(connector_tools)
            except Exception:
                logger.debug("connector_tools_load_failed", exc_info=True)

        return tools

    async def invoke(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession | None = None,
        actor_user_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        agent_instance_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """Invoke a tool by name with the given arguments.

        ``actor_user_id`` and ``agent_id`` flow through to the connector
        provider for per-user token resolution (P0.2) and per-agent
        authorization (P0.3).
        """
        # Check built-in tools first (infra + plugins)
        if tool_name in _get_all_builtin_tools():
            return await self._invoke_builtin(tool_name, arguments, tenant_id, db=db)

        # Check connector tools (prefix-based routing)
        if tool_name.startswith("connector:") and settings.CONNECTOR_ENABLED and db is not None:
            from app.connectors.agent_bridge import connector_tool_provider

            return await connector_tool_provider.invoke(
                tool_name=tool_name,
                arguments=arguments,
                tenant_id=tenant_id,
                db=db,
                actor_user_id=actor_user_id,
                agent_id=agent_id,
                agent_instance_id=agent_instance_id,
                idempotency_key=idempotency_key,
            )

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
        *,
        db: AsyncSession | None = None,
    ) -> Any:
        """Invoke a built-in platform tool by delegating to MCP tool handlers."""
        logger.info(
            "tool_invoke_builtin",
            tool_name=tool_name,
            tenant_id=str(tenant_id),
        )

        # Load tenant object for MCP tools that require it
        tenant = None
        if db is not None:
            from app.db.models import Tenant

            tenant = await db.get(Tenant, tenant_id)

        if tenant is None:
            # Build a minimal tenant-like object if DB is unavailable
            from types import SimpleNamespace

            tenant = SimpleNamespace(id=tenant_id)

        # Dispatch table: built-in tool name → (handler, kwarg mapping)
        try:
            if tool_name == "ai_complete":
                from app.mcp.tools.ai import ai_complete

                return await ai_complete(
                    model=arguments.get("model", "gpt-4o"),
                    messages=arguments.get("messages", []),
                    max_tokens=arguments.get("max_tokens"),
                    temperature=arguments.get("temperature"),
                    tenant=tenant,
                    db=db,
                )
            elif tool_name == "ai_list_models":
                from app.mcp.tools.ai import ai_list_models

                return await ai_list_models(tenant=tenant, db=db)
            elif tool_name == "rag_search":
                from app.agents.reranker import reranker as _reranker
                from app.agents.search import (
                    SearchFilters,
                    SearchSource,
                    SearchType,
                    hybrid_search_engine,
                )
                from app.db.session import set_tenant_context

                await set_tenant_context(db, str(tenant_id))
                query = arguments.get("query", "")
                sources = [SearchSource(s) for s in arguments.get("sources", ["chunks", "memory"])]
                search_type = SearchType(arguments.get("search_type", "hybrid"))
                filters = SearchFilters(
                    source_types=arguments.get("source_types"),
                )
                limit = min(arguments.get("limit", 10), 50)

                results = await hybrid_search_engine.search(
                    query=query,
                    tenant_id=tenant_id,
                    sources=sources,
                    filters=filters,
                    limit=limit * 3 if arguments.get("rerank") else limit,
                    search_type=search_type,
                    db=db,
                )

                if arguments.get("rerank") and results:
                    docs = [r.content for r in results]
                    reranked = await _reranker.rerank(query=query, documents=docs, top_k=limit)
                    results = [results[rr.index] for rr in reranked if rr.index < len(results)]
                else:
                    results = results[:limit]

                return [
                    {
                        "content": r.content,
                        "score": round(r.score, 4),
                        "source_type": r.source.value,
                        "source_id": r.source_id,
                        "metadata": r.metadata,
                    }
                    for r in results
                ]
            elif tool_name == "file_upload":
                from app.mcp.tools.files import file_upload

                return await file_upload(
                    filename=arguments.get("filename", ""),
                    content_base64=arguments.get("content", ""),
                    tenant=tenant,
                    db=db,
                )
            elif tool_name == "file_list":
                from app.mcp.tools.files import file_list

                return await file_list(tenant=tenant, db=db)
            elif tool_name == "job_create":
                from app.mcp.tools.jobs import job_create

                return await job_create(
                    job_type=arguments.get("job_type", ""),
                    payload=arguments.get("payload"),
                    tenant=tenant,
                    db=db,
                )
            elif tool_name == "job_list":
                from app.mcp.tools.jobs import job_list

                return await job_list(tenant=tenant, db=db)
            elif tool_name == "webhook_create":
                from app.mcp.tools.webhooks import webhook_create

                return await webhook_create(
                    url=arguments.get("url", ""),
                    events=arguments.get("events", []),
                    tenant=tenant,
                    db=db,
                )
            elif tool_name == "code_execute":
                return await self._invoke_sandbox(arguments)
            else:
                # Delegate to plugin tool handlers
                return await self._invoke_plugin_tool(tool_name, arguments, tenant, db)
        except Exception as exc:
            logger.warning(
                "builtin_tool_error",
                tool_name=tool_name,
                error=str(exc),
            )
            return {"error": f"Built-in tool '{tool_name}' failed"}

    async def _invoke_plugin_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant: Any,
        db: AsyncSession | None,
    ) -> Any:
        """Invoke a plugin-contributed agent tool via the plugin registry."""
        if db is None:
            return {"error": f"Tool '{tool_name}' requires a database session"}

        from app.plugins.registry import registry as _plugin_registry

        for plugin in _plugin_registry:
            if tool_name in plugin.get_agent_tool_definitions():
                logger.info(
                    "tool_invoke_plugin",
                    tool_name=tool_name,
                    plugin=plugin.name,
                    tenant_id=str(tenant.id),
                )
                try:
                    result = await plugin.invoke_tool(
                        tool_name,
                        arguments,
                        tenant=tenant,
                        db=db,
                    )
                    if result is not None:
                        return result
                except (ValueError, KeyError, TypeError) as exc:
                    logger.warning(
                        "plugin_tool_validation_error",
                        tool_name=tool_name,
                        plugin=plugin.name,
                        error=str(exc)[:200],
                    )
                    return {"error": f"Invalid input for '{tool_name}': {str(exc)[:200]}"}
                except Exception:
                    logger.error(
                        "plugin_tool_error",
                        tool_name=tool_name,
                        plugin=plugin.name,
                        exc_info=True,
                    )
                    # Roll back the dirty session so subsequent tool calls
                    # don't cascade-fail with PendingRollbackError.
                    with contextlib.suppress(Exception):
                        await db.rollback()
                    return {"error": f"Plugin tool '{tool_name}' failed unexpectedly"}

        return {"error": f"Built-in tool '{tool_name}' has no handler"}

    async def _invoke_sandbox(self, arguments: dict[str, Any]) -> Any:
        """Invoke the code execution sandbox.

        Only available when AGENT_SANDBOX_ENABLED is True.
        """
        from app.config import settings

        if not settings.AGENT_SANDBOX_ENABLED:
            return {"error": "Code execution sandbox is not enabled"}

        code = arguments.get("code", "")
        if not code:
            return {"error": "No code provided"}

        from app.agents.sandbox import ExecutionSandbox, SandboxConfig

        config = SandboxConfig(
            memory_mb=settings.AGENT_SANDBOX_MEMORY_MB,
            cpu_seconds=settings.AGENT_SANDBOX_CPU_SECONDS,
            timeout_seconds=settings.AGENT_SANDBOX_TIMEOUT_SECONDS,
            network_enabled=settings.AGENT_SANDBOX_NETWORK_ENABLED,
        )

        sandbox = ExecutionSandbox(config)
        result = await sandbox.execute_python(
            code,
            input_data=arguments.get("input_data"),
        )

        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_value": result.return_value,
            "duration_ms": result.duration_ms,
            "error": result.error,
        }

    async def _invoke_external(
        self,
        tool: TenantTool,
        arguments: dict[str, Any],
    ) -> Any:
        """Invoke a tenant-registered external tool via HTTP.

        Re-validates the URL at invocation time to prevent SSRF via
        URL modification after initial registration.
        """
        # Re-validate URL at invocation to catch SSRF from modified URLs
        from app.core.url_validation import validate_url

        try:
            validate_url(tool.endpoint_url)
        except ValueError as exc:
            logger.warning(
                "tool_ssrf_blocked",
                tool_name=tool.tool_name,
                endpoint=tool.endpoint_url,
                error=str(exc),
            )
            return {"error": f"Tool '{tool.tool_name}' has an invalid endpoint URL"}

        # Per-tenant circuit breaker key to prevent cross-tenant impact
        breaker_key = f"{tool.tenant_id}:{CircuitBreaker.host_key(tool.endpoint_url)}"

        if _tool_breaker.is_open(breaker_key):
            return {"error": f"Tool '{tool.tool_name}' is temporarily unavailable (circuit open)"}

        try:
            headers = {"Content-Type": "application/json"}

            # Apply auth config if present, decrypting secrets
            auth_config = tool.auth_config or {}
            if auth_config.get("type") == "bearer":
                token = auth_config.get("token", "")
                if token:
                    try:
                        from app.core.encryption import decrypt

                        token = decrypt(token)
                    except Exception:
                        logger.error("tool_auth_token_decrypt_failed", tool_name=tool.tool_name)
                        return {"error": f"Tool '{tool.tool_name}' has invalid authentication credentials"}
                headers["Authorization"] = f"Bearer {token}"
            elif auth_config.get("type") == "api_key":
                header_name = auth_config.get("header", "X-API-Key")
                key = auth_config.get("key", "")
                if key:
                    try:
                        from app.core.encryption import decrypt

                        key = decrypt(key)
                    except Exception:
                        logger.error("tool_auth_key_decrypt_failed", tool_name=tool.tool_name)
                        return {"error": f"Tool '{tool.tool_name}' has invalid authentication credentials"}
                # Validate header name to prevent HTTP header injection
                import re

                _SAFE_HEADER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]*$")
                _DENIED_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "authorization"}
                if not _SAFE_HEADER_RE.match(header_name) or header_name.lower() in _DENIED_HEADERS:
                    logger.warning(
                        "tool_auth_invalid_header",
                        tool_name=tool.tool_name,
                        header=header_name,
                    )
                    return {"error": f"Tool '{tool.tool_name}' has an invalid auth header name"}
                headers[header_name] = key

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0),
            ) as client:
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

    # ── Supply Chain Verification ──────────────────────────────────────

    @staticmethod
    def compute_schema_hash(tool: TenantTool) -> str:
        """Compute a deterministic hash of a tool's input/output schema."""
        schema_data = json.dumps(
            {
                "input_schema": tool.input_schema or {},
                "output_schema": tool.output_schema or {},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(schema_data.encode()).hexdigest()[:16]

    async def verify_tool_schema(
        self,
        tool: TenantTool,
        db: AsyncSession,
    ) -> tuple[bool, str]:
        """Verify a tool's schema hasn't drifted from its registered hash.

        Returns (is_valid, reason).
        """
        if not settings.AGENT_TOOL_SCHEMA_VERIFICATION:
            return True, ""

        if not tool.schema_hash:
            # First invocation — set the hash
            tool.schema_hash = self.compute_schema_hash(tool)
            await db.flush()
            return True, ""

        current_hash = self.compute_schema_hash(tool)
        if current_hash != tool.schema_hash:
            logger.warning(
                "tool_schema_drift_detected",
                tool_name=tool.tool_name,
                tenant_id=str(tool.tenant_id),
                expected_hash=tool.schema_hash,
                actual_hash=current_hash,
            )
            # Emit event
            try:
                from app.agents.events import ToolSchemaViolation
                from app.core.events import emit

                await emit(
                    ToolSchemaViolation(
                        tenant_id=str(tool.tenant_id),
                        tool_name=tool.tool_name,
                        expected_hash=tool.schema_hash,
                        actual_hash=current_hash,
                    ),
                    durable=True,
                )
            except Exception:
                pass
            return False, f"Schema drift: expected {tool.schema_hash}, got {current_hash}"

        return True, ""

    def verify_tool_response_signature(
        self,
        tool: TenantTool,
        response_body: bytes,
        signature_header: str,
    ) -> bool:
        """Verify the HMAC signature of an external tool's response."""
        if not tool.tool_signature_secret_encrypted:
            return True  # No signature verification configured

        try:
            from app.core.encryption import decrypt

            secret = decrypt(tool.tool_signature_secret_encrypted)
        except Exception:
            logger.warning("tool_signature_secret_decrypt_failed", tool_name=tool.tool_name)
            return False

        expected = hmac.new(
            secret.encode(),
            response_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    async def record_tool_behavior(
        self,
        *,
        tenant_id: uuid.UUID,
        tool_name: str,
        latency_ms: int,
        response_size: int,
        success: bool,
    ) -> None:
        """Record behavioral metrics for tool anomaly detection."""
        if not settings.AGENT_TOOL_BEHAVIORAL_MONITORING:
            return

        behavior_key = _TOOL_BEHAVIOR_KEY.format(
            tenant_id=tenant_id,
            tool_name=tool_name,
        )
        try:
            entry = json.dumps(
                {
                    "ts": time.time(),
                    "latency_ms": latency_ms,
                    "size": response_size,
                    "ok": success,
                }
            )
            pipe = redis_pool.pipeline()
            pipe.lpush(behavior_key, entry)
            pipe.ltrim(behavior_key, 0, 99)  # Keep last 100 entries
            pipe.expire(behavior_key, 86400)
            await pipe.execute()
        except Exception:
            logger.debug("tool_behavior_record_failed", exc_info=True)

    async def check_tool_behavioral_anomaly(
        self,
        tenant_id: uuid.UUID,
        tool_name: str,
        latency_ms: int,
    ) -> bool:
        """Check if a tool's current behavior is anomalous.

        Returns True if anomalous (sudden latency spike = possible supply chain compromise).
        """
        if not settings.AGENT_TOOL_BEHAVIORAL_MONITORING:
            return False

        behavior_key = _TOOL_BEHAVIOR_KEY.format(
            tenant_id=tenant_id,
            tool_name=tool_name,
        )
        try:
            entries_raw = await redis_pool.lrange(behavior_key, 0, 49)
            if len(entries_raw) < 5:
                return False  # Not enough data

            latencies = []
            for raw in entries_raw:
                entry = json.loads(raw)
                latencies.append(entry["latency_ms"])

            avg = sum(latencies) / len(latencies)
            if avg == 0:
                return False

            # Flag if current latency is >5x the average
            if latency_ms > avg * 5:
                logger.warning(
                    "tool_behavioral_anomaly",
                    tool_name=tool_name,
                    current_latency=latency_ms,
                    avg_latency=avg,
                    ratio=latency_ms / avg,
                )
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def get_trust_level_checks(trust_level: str) -> dict[str, bool]:
        """Return which governance checks to apply based on tool trust level."""
        if trust_level == "verified":
            return {"governance_check": False, "schema_verify": False, "signature_verify": False}
        elif trust_level == "trusted":
            return {"governance_check": False, "schema_verify": True, "signature_verify": False}
        else:  # untrusted
            return {"governance_check": True, "schema_verify": True, "signature_verify": True}

    async def health_check(
        self,
        tool: TenantTool,
    ) -> dict[str, Any]:
        """Check the health of an external tool."""
        if not tool.health_check_url:
            return {"status": "unknown", "reason": "no health check URL configured"}

        # Validate URL to prevent SSRF (same as _invoke_external)
        from app.core.url_validation import validate_url

        try:
            validate_url(tool.health_check_url)
        except ValueError as exc:
            logger.warning(
                "tool_health_check_ssrf_blocked",
                tool_name=tool.tool_name,
                url=tool.health_check_url,
                error=str(exc),
            )
            return {"status": "error", "reason": "Invalid health check URL"}

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
