"""Redis-backed idempotency for POST/PUT/PATCH endpoints.

Prevents duplicate side effects when clients retry requests due to network
issues or timeouts. Uses the X-Idempotency-Key header as the deduplication key.

Usage as a FastAPI dependency:
    from app.core.idempotency import IdempotencyGuard

    @router.post("/payments")
    async def create_payment(
        request: Request,
        _idem=Depends(IdempotencyGuard(ttl=86400)),
    ):
        ...
"""

import json

import structlog
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

_KEY_PREFIX = "idempotency:"


class IdempotencyGuard:
    """FastAPI dependency that enforces idempotency via X-Idempotency-Key header.

    On first request: stores the response in Redis with a TTL.
    On duplicate request: returns the cached response without re-executing the handler.
    """

    def __init__(self, ttl: int = 86400, required: bool = False):
        """
        Args:
            ttl: How long to remember the idempotency key (seconds). Default 24h.
            required: If True, reject requests without X-Idempotency-Key.
        """
        self.ttl = ttl
        self.required = required

    async def __call__(self, request: Request) -> None:
        idem_key = request.headers.get("X-Idempotency-Key", "").strip()

        if not idem_key:
            if self.required:
                raise HTTPException(
                    status_code=400,
                    detail="X-Idempotency-Key header is required for this endpoint",
                )
            return

        # Validate key format (prevent abuse with very long keys)
        if len(idem_key) > 255:
            raise HTTPException(
                status_code=400,
                detail="X-Idempotency-Key must be at most 255 characters",
            )

        # Scope to tenant if available
        tenant = getattr(request.state, "tenant", None)
        scope = str(tenant.id) if tenant else "global"
        redis_key = f"{_KEY_PREFIX}{scope}:{idem_key}"

        try:
            cached = await redis_pool.get(redis_key)
            if cached is not None:
                data = json.loads(cached)
                logger.info("idempotency_cache_hit", key=idem_key)
                # Return cached response directly by storing it for middleware
                request.state.idempotency_response = JSONResponse(
                    status_code=data["status_code"],
                    content=data["body"],
                    headers={"X-Idempotent-Replayed": "true"},
                )
                return
        except Exception:
            logger.warning("idempotency_redis_error", key=idem_key)

        # Store key and TTL on request state for post-response caching
        request.state.idempotency_key = redis_key
        request.state.idempotency_ttl = self.ttl


async def store_idempotent_response(request: Request, status_code: int, body: dict) -> None:
    """Store the response for an idempotent request. Call after successful processing."""
    redis_key = getattr(request.state, "idempotency_key", None)
    ttl = getattr(request.state, "idempotency_ttl", 86400)

    if not redis_key:
        return

    try:
        data = json.dumps({"status_code": status_code, "body": body}, default=str)
        await redis_pool.setex(redis_key, ttl, data)
    except Exception:
        logger.warning("idempotency_store_error", key=redis_key)
