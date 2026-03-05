"""Redis sliding-window rate limiter with in-memory fallback.

Uses a sorted set per client key with timestamps as scores.
Each request adds the current timestamp and prunes entries outside the window.

When Redis is unavailable, falls back to a process-local in-memory counter
to maintain basic rate limiting (less precise, but still enforced).

Usage as a FastAPI dependency:
    from app.api.rate_limit import RateLimiter

    @router.post("/login")
    async def login(request: Request, _rl=Depends(RateLimiter(max_requests=10, window=60))):
        ...
"""

import threading
import time
from collections import defaultdict

import structlog
from fastapi import HTTPException, Request

from app.config import settings
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()


class _InMemoryRateLimitStore:
    """Thread-safe in-memory fallback for when Redis is unavailable.

    Uses a dict of lists of timestamps per key. Periodically prunes old entries.
    This is a best-effort fallback — it is per-process and not shared across
    multiple API server instances.
    """

    def __init__(self) -> None:
        self._store: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check_and_increment(self, key: str, window: float) -> int:
        """Return the current request count after adding one. Prunes old entries."""
        now = time.time()
        cutoff = now - window

        with self._lock:
            entries = self._store[key]
            # Prune entries outside the window
            self._store[key] = [t for t in entries if t > cutoff]
            self._store[key].append(now)
            return len(self._store[key])


_fallback_store = _InMemoryRateLimitStore()


class RateLimiter:
    """Callable FastAPI dependency for per-IP sliding-window rate limiting."""

    def __init__(
        self,
        max_requests: int | None = None,
        window: int | None = None,
        key_prefix: str = "rl",
    ):
        self.max_requests = max_requests or settings.RATE_LIMIT_DEFAULT
        self.window = window or settings.RATE_LIMIT_WINDOW_SECONDS
        self.key_prefix = key_prefix

    async def __call__(self, request: Request) -> None:
        # Identify client by IP (or X-Forwarded-For behind a proxy)
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        key = f"{self.key_prefix}:{client_ip}:{request.url.path}"
        now = time.time()
        window_start = now - self.window

        try:
            pipe = redis_pool.pipeline()
            # Remove entries outside the window
            pipe.zremrangebyscore(key, 0, window_start)
            # Count remaining entries
            pipe.zcard(key)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Set TTL on the key
            pipe.expire(key, self.window)
            results = await pipe.execute()
            request_count = results[1]
        except Exception:
            # Redis unavailable — fall back to in-memory rate limiting
            logger.warning("rate_limit_redis_fallback", client_ip=client_ip)
            request_count = _fallback_store.check_and_increment(key, self.window)

        if request_count >= self.max_requests:
            retry_after = int(self.window - (now - window_start))
            logger.warning(
                "rate_limit_exceeded",
                client_ip=client_ip,
                path=request.url.path,
                count=request_count,
                limit=self.max_requests,
            )
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={"Retry-After": str(max(1, retry_after))},
            )
