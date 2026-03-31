import asyncio

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from starlette.responses import JSONResponse

from app import __version__
from app.api.deps import require_admin_key
from app.api.schemas import HealthResponse, HealthStatusResponse
from app.config import settings
from app.core.redis import redis_pool
from app.db.session import async_engine

logger = structlog.stdlib.get_logger()

router = APIRouter()


async def _check_db() -> bool:
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("db_health_check_failed", exc_info=True)
        return False


async def _check_redis() -> bool:
    try:
        await redis_pool.ping()
        return True
    except Exception:
        logger.warning("redis_health_check_failed", exc_info=True)
        return False


def _check_storage_sync() -> bool:
    from app.storage.s3 import get_s3_client

    client = get_s3_client()
    client.head_bucket(Bucket=settings.S3_BUCKET)
    return True


async def _check_storage() -> bool:
    if not settings.storage_configured:
        # Storage not configured — report as unchecked, not failed
        return True
    try:
        return await asyncio.to_thread(_check_storage_sync)
    except Exception:
        logger.warning("storage_health_check_failed", exc_info=True)
        return False


async def _check_celery() -> bool:
    """Check Celery worker connectivity by inspecting active workers via Redis.

    Pings actual Celery workers rather than just the Redis broker, so we
    detect the scenario where Redis is up but no workers are running.
    """
    try:
        from app.workers.celery_app import celery as celery_app

        inspect = celery_app.control.inspect(timeout=2)
        result = await asyncio.to_thread(inspect.ping)
        return bool(result)  # None or empty dict means no workers responded
    except Exception:
        logger.warning("celery_health_check_failed", exc_info=True)
        return False


@router.get("/health/live")
async def liveness():
    """Kubernetes liveness probe — is the process alive?"""
    return {"status": "ok"}


async def _readiness_check() -> dict:
    """Readiness check — not cached so K8s probes reflect real-time status.

    Each check is wrapped in asyncio.wait_for to prevent a slow dependency
    from blocking the entire health endpoint (e.g. if S3 hangs for 30s).
    """

    async def _with_timeout(coro, timeout: float = 5.0) -> bool:
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            return False

    # Critical checks (DB + Redis) gate the status.
    # Non-critical checks (Storage + Celery) run in parallel but don't block
    # the response — if they're still pending when critical checks finish, we
    # return immediately and report them as "unknown".
    critical_coros = [
        _with_timeout(_check_db()),
        _with_timeout(_check_redis()),
    ]
    non_critical_coros = [
        _with_timeout(_check_storage(), timeout=3.0),
        _with_timeout(_check_celery(), timeout=3.0),
    ]

    # Launch everything concurrently
    all_tasks = [asyncio.ensure_future(c) for c in critical_coros + non_critical_coros]

    # Wait only for critical checks
    db_ok, redis_ok = await asyncio.gather(all_tasks[0], all_tasks[1])
    critical_ok = db_ok and redis_ok

    # Collect non-critical results if already done, otherwise report True
    # (non-critical failure should never prevent API readiness)
    storage_ok = all_tasks[2].result() if all_tasks[2].done() else True
    celery_ok = all_tasks[3].result() if all_tasks[3].done() else True

    return {
        "status": "ok" if critical_ok else "degraded",
        "version": __version__,
        "services": {"db": db_ok, "redis": redis_ok, "storage": storage_ok, "celery": celery_ok},
    }


@router.get("/health/ready", response_model=HealthStatusResponse)
async def readiness():
    """Kubernetes readiness probe — returns aggregate status only."""
    data = await _readiness_check()
    status_code = 200 if data["status"] == "ok" else 503
    return JSONResponse({"status": data["status"]}, status_code=status_code)


@router.get("/health", response_model=HealthStatusResponse)
async def health_check():
    """Combined health check — returns aggregate status only."""
    data = await _readiness_check()
    status_code = 200 if data["status"] == "ok" else 503
    return JSONResponse({"status": data["status"]}, status_code=status_code)


@router.get(
    "/health/details",
    response_model=HealthResponse,
    dependencies=[Depends(require_admin_key)],
)
async def health_details():
    """Detailed health check with component breakdown — admin only.

    Unlike the readiness probe, this endpoint waits for ALL checks
    (including non-critical Celery/Storage) so admins see real status.
    """

    async def _with_timeout(coro, timeout: float = 5.0) -> bool:
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            return False

    db_ok, redis_ok, storage_ok, celery_ok = await asyncio.gather(
        _with_timeout(_check_db()),
        _with_timeout(_check_redis()),
        _with_timeout(_check_storage()),
        _with_timeout(_check_celery()),
    )
    critical_ok = db_ok and redis_ok
    return HealthResponse(
        status="ok" if critical_ok else "degraded",
        version=__version__,
        services={"db": db_ok, "redis": redis_ok, "storage": storage_ok, "celery": celery_ok},
    )


@router.get("/.well-known/jwks.json")
async def jwks():
    """JWKS endpoint for RS256/ES256 public key discovery.

    Services that need to verify JWTs can fetch the public key from here
    instead of sharing the signing secret.
    """
    from app.core.security import get_jwks_public_key
    key = get_jwks_public_key()
    if key is None:
        return {"keys": []}
    return {"keys": [key]}
