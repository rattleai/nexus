"""Bridge between FastAPI routes and MCP tools via fastapi-mcp.

Auto-exposes tenant-facing FastAPI endpoints as MCP tools alongside the
hand-written tools in server.py. This means new API routes automatically
become available over MCP without duplicating tool definitions.

Usage (from app.main or lifespan):
    from app.mcp.api_bridge import mount_api_mcp
    mount_api_mcp(app)

The hand-written tools remain authoritative — they have richer descriptions,
LLM-optimized annotations, and custom auth wiring. Auto-exposed tools serve
as a catch-all so new endpoints are immediately usable.
"""

from __future__ import annotations

import structlog
from fastapi import Depends, FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

logger = structlog.stdlib.get_logger()

# Tags whose routes are allowed to be auto-exposed.
# Using an allowlist (not a denylist) so new sensitive tags default to hidden.
_ALLOWED_TAGS = frozenset({
    "jobs",
    "files",
    "billing",
    "webhooks",
    "ai",
    "agents",
    "api-keys",
    "team",
})

# Path prefixes that are allowed to be auto-exposed as MCP tools.
# Only tenant-facing API routes under /api/v1 with known-safe segments.
_ALLOWED_PATH_PREFIXES = (
    "/api/v1/jobs",
    "/api/v1/files",
    "/api/v1/billing",
    "/api/v1/webhooks",
    "/api/v1/ai",
    "/api/v1/agents",
    "/api/v1/api-keys",
    "/api/v1/team",
)

# Operation IDs of hand-written tools that should take precedence.
# If an auto-generated tool would conflict, it's skipped.
_HANDWRITTEN_OPERATION_IDS = frozenset({
    "ai_complete",
    "ai_list_models",
    "ai_get_usage",
    "job_create",
    "job_list",
    "job_get",
    "job_cancel",
    "billing_get_wallet_balance",
    "billing_list_plans",
    "billing_get_subscription",
    "file_upload",
    "file_download",
    "file_list",
    "team_list_members",
    "team_invite",
    "webhook_list",
    "webhook_create",
    "webhook_delete",
})


def _should_include_operation(
    operation_id: str | None,
    path: str,
    tags: list[str] | None,
) -> bool:
    """Decide whether a FastAPI operation should be auto-exposed as an MCP tool.

    Uses an allowlist approach: both the path prefix AND at least one tag must
    be in the allowed sets. This ensures new admin/internal routes are excluded
    by default.
    """
    # Skip hand-written tools (they have richer descriptions)
    if operation_id and operation_id in _HANDWRITTEN_OPERATION_IDS:
        return False

    # Path must start with a known-safe prefix
    if not any(path.startswith(prefix) for prefix in _ALLOWED_PATH_PREFIXES):
        return False

    # At least one tag must be in the allowlist
    if not tags or not _ALLOWED_TAGS.intersection(t.lower() for t in tags):
        return False

    return True


class _MCPAuthMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated requests to /mcp.

    Checks for a valid X-API-Key header before allowing the request through.
    This ensures the MCP bridge has the same auth gate as the hand-written
    MCP server.
    """

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        x_api_key = request.headers.get("X-API-Key")
        if not x_api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "X-API-Key header required for MCP bridge"},
            )

        # Validate the key and resolve tenant
        from app.api.auth import hash_api_key
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.db.models import ApiKey
        from app.db.session import async_session_factory

        key_hash = hash_api_key(x_api_key)
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(ApiKey)
                    .options(selectinload(ApiKey.tenant))
                    .where(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
                )
                api_key = result.scalar_one_or_none()

                if api_key is None:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Invalid API key"},
                    )

                tenant = api_key.tenant
                if tenant is None or not tenant.is_active:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Tenant not found or inactive"},
                    )

                # Rate limit keyed by tenant
                from app.api.rate_limit import _check_rate

                rate_key = f"rl:mcp-bridge:{tenant.id}"
                count = await _check_rate(
                    rate_key,
                    settings.MCP_RATE_LIMIT_REQUESTS,
                    60,
                )
                if count >= settings.MCP_RATE_LIMIT_REQUESTS:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "MCP bridge rate limit exceeded"},
                        headers={
                            "Retry-After": "60",
                            "RateLimit-Policy": f"{settings.MCP_RATE_LIMIT_REQUESTS};w=60",
                        },
                    )

                # Store tenant info for downstream use
                request.state.api_key = api_key
                request.state.tenant = tenant

        except Exception:
            logger.exception("mcp_bridge_auth_error")
            return JSONResponse(
                status_code=500,
                content={"detail": "Authentication error"},
            )

        return await call_next(request)


def mount_api_mcp(app: FastAPI) -> None:
    """Mount fastapi-mcp on the FastAPI app to auto-expose routes as MCP tools.

    This adds a /mcp endpoint on the main FastAPI app that speaks the MCP
    protocol (SSE transport), complementing the standalone MCP server on port
    8001 that uses stdio/HTTP transport.

    Call this AFTER all routers and schema enrichment have been registered.
    """
    if not settings.MCP_ENABLED or not settings.MCP_EXPOSE_API_ROUTES:
        logger.debug("mcp_api_bridge_disabled")
        return

    try:
        from fastapi_mcp import FastApiMCP
    except ImportError:
        logger.warning(
            "mcp_api_bridge_unavailable",
            detail="fastapi-mcp not installed. Run: pip install 'fastapi-mcp>=0.5'",
        )
        return

    # Add auth + rate limiting middleware for /mcp paths
    app.add_middleware(_MCPAuthMiddleware)

    # Build an operation filter using the allowlist approach
    def operation_filter(
        operation_id: str | None,
        path: str,
        method: str,
        tags: list[str] | None = None,
    ) -> bool:
        return _should_include_operation(operation_id, path, tags)

    mcp = FastApiMCP(
        app,
        name=f"{settings.MCP_SERVER_NAME}-api",
        description=(
            "Auto-generated MCP tools from CADPrice REST API endpoints. "
            "These complement the hand-written MCP tools with richer descriptions."
        ),
        describe_all_responses=True,
        describe_full_response_schema=False,
        operation_filter=operation_filter,
    )

    mcp.mount(app, mount_path="/mcp")

    # Collect exposed tool count for logging
    tool_count = len(mcp.tools) if hasattr(mcp, "tools") else "unknown"
    logger.info(
        "mcp_api_bridge_mounted",
        mount_path="/mcp",
        tool_count=tool_count,
    )
