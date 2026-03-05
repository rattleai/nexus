"""Redis sliding-window rate limiter.

Uses a sorted set per client key with timestamps as scores.
Each request adds the current timestamp and prunes entries outside the window.

Usage as a FastAPI dependency:
    from app.api.rate_limit import RateLimiter

    @router.post("/login")
    async def login(request: Request, _rl=Depends(RateLimiter(max_requests=10, window=60))):
        ...
"""

import time

import structlog
from fastapi import HTTPException, Request

from app.config import settings
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()


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
            # If Redis is down, allow the request (fail-open for rate limiting)
            logger.warning("rate_limit_redis_error", client_ip=client_ip)
            return

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
