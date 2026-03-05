"""Redis caching layer with decorator-based API.

Provides:
- @cached(ttl, key, group) decorator for async functions
- Graceful degradation when Redis is unavailable
- Cache invalidation by exact key or glob pattern
- Cache-Control: no-cache bypass support via request.state.cache_bypass
"""

import functools
import hashlib
import json
from typing import Any, Callable

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()

CACHE_TTLS: dict[str, int] = {
    "default": 300,
    "health": 10,
    "tenant": 600,
    "job_status": 60,
}

_PREFIX = "cache:"


def _build_key(template: str, args: tuple, kwargs: dict) -> str:
    """Build cache key from template and function arguments."""
    try:
        return f"{_PREFIX}{template.format(*args, **kwargs)}"
    except (KeyError, IndexError):
        raw = json.dumps({"a": args, "k": kwargs}, sort_keys=True, default=str)
        h = hashlib.sha256(raw.encode()).hexdigest()[:32]
        return f"{_PREFIX}{template}:{h}"


def cached(ttl: int | None = None, key: str = "", group: str = "default") -> Callable:
    """Cache decorator for async functions.

    Args:
        ttl: Cache TTL in seconds. Defaults to the group's preset.
        key: Key template with format placeholders (e.g. "tenants:{tenant_id}").
        group: TTL preset group name.
    """
    effective_ttl = ttl or CACHE_TTLS.get(group, CACHE_TTLS["default"])

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not settings.CACHE_ENABLED:
                return await func(*args, **kwargs)

            # Check for cache bypass via request.state
            for arg in args:
                if hasattr(arg, "state") and getattr(arg.state, "cache_bypass", False):
                    return await func(*args, **kwargs)
            for v in kwargs.values():
                if hasattr(v, "state") and getattr(v.state, "cache_bypass", False):
                    return await func(*args, **kwargs)

            cache_key = _build_key(key or func.__qualname__, args, kwargs)

            # Lazy import to avoid circular dependency at module load
            from app.core.redis import redis_pool

            # Try cache read
            try:
                cached_value = await redis_pool.get(cache_key)
                if cached_value is not None:
                    return json.loads(cached_value)
            except Exception:
                logger.warning("cache_read_error", key=cache_key)

            # Cache miss — call the function
            result = await func(*args, **kwargs)

            # Write to cache
            try:
                serialized = json.dumps(result, default=str)
                await redis_pool.setex(cache_key, effective_ttl, serialized)
            except Exception:
                logger.warning("cache_write_error", key=cache_key)

            return result

        wrapper.cache_key_template = key or func.__qualname__  # type: ignore[attr-defined]
        return wrapper

    return decorator


async def invalidate(pattern: str) -> int:
    """Invalidate cache entries by exact key or glob pattern.

    Args:
        pattern: Key (without prefix) or glob pattern, e.g. "tenants:*".

    Returns:
        Number of keys deleted.
    """
    from app.core.redis import redis_pool

    full_pattern = f"{_PREFIX}{pattern}"
    try:
        if "*" in full_pattern:
            count = 0
            async for key in redis_pool.scan_iter(match=full_pattern, count=100):
                await redis_pool.delete(key)
                count += 1
            return count
        else:
            return await redis_pool.delete(full_pattern)
    except Exception:
        logger.warning("cache_invalidate_error", pattern=pattern)
        return 0
