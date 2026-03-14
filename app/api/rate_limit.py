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

_MAX_TRACKED_KEYS = 100_000


class _InMemoryRateLimitStore:
    """Thread-safe in-memory fallback for when Redis is unavailable.

    Uses a dict of lists of timestamps per key. Prunes old entries and evicts
    stale keys to prevent unbounded memory growth.
    """

    def __init__(self) -> None:
        self._store: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check_and_increment(self, key: str, window: float) -> int:
        """Return the current request count after adding one. Prunes old entries."""
        now = time.time()
        cutoff = now - window

        with self._lock:
            # Evict stale keys periodically to prevent memory leak
            if len(self._store) > _MAX_TRACKED_KEYS:
                stale_keys = [k for k, v in self._store.items() if not v or v[-1] < cutoff]
                for k in stale_keys:
                    del self._store[k]

            entries = self._store[key]
            # Prune entries outside the window
            self._store[key] = [t for t in entries if t > cutoff]
            self._store[key].append(now)
            return len(self._store[key])


_fallback_store = _InMemoryRateLimitStore()


def _get_client_ip(request: Request) -> str:
    """Extract client IP, trusting X-Real-IP only from localhost proxies."""
    direct_ip = request.client.host if request.client else "unknown"
    forwarded_ip = request.headers.get("X-Real-IP", "").strip()
    if forwarded_ip and direct_ip in ("127.0.0.1", "::1"):
        return forwarded_ip
    return direct_ip


async def _check_rate(key: str, max_requests: int, window: int) -> int:
    """Check rate limit and return current request count."""
    now = time.time()
    window_start = now - window

    try:
        pipe = redis_pool.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window)
        results = await pipe.execute()
        return results[2]
    except Exception:
        logger.warning("rate_limit_redis_fallback", key=key)
        return _fallback_store.check_and_increment(key, window)


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
        client_ip = _get_client_ip(request)
        # Normalize path to prevent bypass via trailing slashes, double slashes, or casing
        normalized_path = request.url.path.rstrip("/").lower().replace("//", "/")
        key = f"{self.key_prefix}:{client_ip}:{normalized_path}"
        request_count = await _check_rate(key, self.max_requests, self.window)

        # Store rate limit info on request state for response headers (P1-12)
        remaining = max(0, self.max_requests - request_count)
        request.state.rate_limit_limit = self.max_requests
        request.state.rate_limit_remaining = remaining
        request.state.rate_limit_reset = int(time.time()) + self.window

        if request_count > self.max_requests:
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
                headers={
                    "Retry-After": str(self.window),
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + self.window),
                },
            )


# Known agent User-Agent prefixes
AGENT_UA_PREFIXES = (
    "mcp-client/",
    "claude-code/",
    "openai-agent/",
    "cadprice-cli/",
    "github-copilot/",
    "cursor/",
)


def is_agent_request(request: Request) -> bool:
    """Detect if the request comes from an AI agent.

    Checks for X-Agent-Name header, X-API-Key header (programmatic access),
    or known agent User-Agent patterns. Result is cached on request.state.
    """
    # Return cached result if already computed
    cached = getattr(request.state, "is_agent", None)
    if cached is not None:
        return cached

    if request.headers.get("X-Agent-Name"):
        result = True
    elif request.headers.get("X-API-Key"):
        # API key auth implies programmatic access — treat as agent
        result = True
    else:
        ua = request.headers.get("User-Agent", "").lower()
        result = any(ua.startswith(prefix) for prefix in AGENT_UA_PREFIXES)

    request.state.is_agent = result
    return result


# Backward-compatible alias
_is_agent_request = is_agent_request


class AgentAwareRateLimiter:
    """Rate limiter that applies higher limits to identified agent traffic.

    Agents are identified by User-Agent patterns or the X-Agent-Name header.
    Non-agent traffic uses the standard rate limit.
    """

    def __init__(
        self,
        max_requests: int | None = None,
        agent_max_requests: int | None = None,
        window: int | None = None,
        key_prefix: str = "rl",
    ):
        self.max_requests = max_requests or settings.RATE_LIMIT_DEFAULT
        self.agent_max_requests = agent_max_requests or settings.AGENT_RATE_LIMIT_REQUESTS
        self.window = window or settings.RATE_LIMIT_WINDOW_SECONDS
        self.key_prefix = key_prefix

    async def __call__(self, request: Request) -> None:
        is_agent = _is_agent_request(request)
        effective_limit = self.agent_max_requests if is_agent else self.max_requests
        effective_window = settings.AGENT_RATE_LIMIT_WINDOW_SECONDS if is_agent else self.window

        client_ip = _get_client_ip(request)
        normalized_path = request.url.path.rstrip("/").lower().replace("//", "/")
        tier = "agent" if is_agent else "std"
        key = f"{self.key_prefix}:{tier}:{client_ip}:{normalized_path}"

        request_count = await _check_rate(key, effective_limit, effective_window)

        remaining = max(0, effective_limit - request_count)
        request.state.rate_limit_limit = effective_limit
        request.state.rate_limit_remaining = remaining
        request.state.rate_limit_reset = int(time.time()) + effective_window

        if request_count > effective_limit:
            logger.warning(
                "rate_limit_exceeded",
                client_ip=client_ip,
                path=request.url.path,
                count=request_count,
                limit=effective_limit,
                is_agent=is_agent,
            )
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={
                    "Retry-After": str(effective_window),
                    "X-RateLimit-Limit": str(effective_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + effective_window),
                },
            )


class ApiKeyRateLimiter:
    """Per-API-key rate limiter that uses the key's configured rate_limit.

    Falls back to the global default if the API key has no custom limit.
    Must be used after get_current_api_key dependency resolves the key.
    """

    async def __call__(self, request: Request) -> None:
        # The API key is resolved by dependency injection before this runs.
        # Access it from request state if available, otherwise skip.
        api_key = getattr(request.state, "api_key", None)
        if api_key is None:
            return

        max_requests = api_key.rate_limit or settings.RATE_LIMIT_DEFAULT
        window = settings.RATE_LIMIT_WINDOW_SECONDS
        key = f"rl:apikey:{api_key.id}"

        request_count = await _check_rate(key, max_requests, window)

        if request_count > max_requests:
            logger.warning(
                "api_key_rate_limit_exceeded",
                key_id=str(api_key.id),
                count=request_count,
                limit=max_requests,
            )
            raise HTTPException(
                status_code=429,
                detail="API key rate limit exceeded",
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                },
            )
