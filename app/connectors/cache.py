"""Three-layer caching for connector tools.

Layer 1: Database — TenantConnection.mcp_tools_cache (persists across restarts)
Layer 2: Redis — aggregated tool list per tenant (fast, TTL-based)
Layer 3: Process memory — populated per agent run (not implemented here;
         the agent runtime caches tools per-run naturally)

This module manages Layer 2 (Redis).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from app.config import settings
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

_CACHE_KEY_PREFIX = "connector:tools"


def _cache_key(tenant_id: uuid.UUID) -> str:
    return f"{_CACHE_KEY_PREFIX}:{tenant_id}"


class ConnectorToolCache:
    """Redis-backed cache for per-tenant connector tool lists."""

    async def get_tools(self, tenant_id: uuid.UUID) -> list[dict[str, Any]] | None:
        """Get cached tools for a tenant. Returns None on cache miss."""
        try:
            raw = await redis_pool.get(_cache_key(tenant_id))
            if raw:
                return json.loads(raw)
        except Exception:
            logger.debug("connector_cache_get_failed", exc_info=True)
        return None

    async def set_tools(
        self,
        tenant_id: uuid.UUID,
        tools: list[dict[str, Any]],
    ) -> None:
        """Cache the tool list for a tenant with TTL."""
        try:
            ttl = settings.CONNECTOR_TOOL_CACHE_TTL_SECONDS
            await redis_pool.setex(
                _cache_key(tenant_id),
                ttl,
                json.dumps(tools, default=str),
            )
        except Exception:
            logger.debug("connector_cache_set_failed", exc_info=True)

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """Invalidate the cached tools for a tenant."""
        try:
            await redis_pool.delete(_cache_key(tenant_id))
        except Exception:
            logger.debug("connector_cache_invalidate_failed", exc_info=True)

    async def invalidate_all(self) -> None:
        """Invalidate all cached connector tools (for admin/testing)."""
        try:
            keys = []
            async for key in redis_pool.scan_iter(f"{_CACHE_KEY_PREFIX}:*"):
                keys.append(key)
            if keys:
                await redis_pool.delete(*keys)
        except Exception:
            logger.debug("connector_cache_invalidate_all_failed", exc_info=True)


# Module-level singleton
connector_tool_cache = ConnectorToolCache()
