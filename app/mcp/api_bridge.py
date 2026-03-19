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
from fastapi import FastAPI

from app.config import settings

logger = structlog.stdlib.get_logger()

# Tags whose routes should NOT be auto-exposed (already covered by hand-written
# MCP tools, or are internal/admin-only).
_EXCLUDED_TAGS = frozenset({
    "admin",
    "tenants",
    "metrics",
    "health",
    "websocket",
})

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


def _should_include_operation(operation_id: str | None, tags: list[str] | None) -> bool:
    """Decide whether a FastAPI operation should be auto-exposed as an MCP tool."""
    if operation_id and operation_id in _HANDWRITTEN_OPERATION_IDS:
        return False
    if tags and _EXCLUDED_TAGS.intersection(t.lower() for t in tags):
        return False
    return True


def mount_api_mcp(app: FastAPI) -> None:
    """Mount fastapi-mcp on the FastAPI app to auto-expose routes as MCP tools.

    This adds a /mcp endpoint on the main FastAPI app that speaks the MCP
    protocol (SSE transport), complementing the standalone MCP server on port
    8001 that uses stdio/HTTP transport.

    Call this AFTER all routers have been registered on the app.
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

    # Build an operation filter from the excluded tags / hand-written IDs
    def operation_filter(operation_id: str | None, path: str, method: str, tags: list[str] | None = None) -> bool:
        # Exclude internal paths
        if path.startswith(("/admin", "/tenants", "/metrics")):
            return False
        return _should_include_operation(operation_id, tags)

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
