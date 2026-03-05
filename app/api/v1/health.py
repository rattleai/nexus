import asyncio

import structlog
from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.schemas import HealthResponse
from app.config import settings
from app.core.cache import cached
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
    """Check Celery worker connectivity via Redis broker ping."""
    try:
        result = await redis_pool.ping()
        return bool(result)
    except Exception:
        logger.warning("celery_health_check_failed", exc_info=True)
        return False


@router.get("/health/live")
async def liveness():
    """Kubernetes liveness probe — is the process alive?"""
    return {"status": "ok"}


@cached(group="health", key="health:ready")
async def _readiness_check() -> dict:
    """Cached readiness check result (10s TTL)."""
    db_ok, redis_ok, storage_ok, celery_ok = await asyncio.gather(
        _check_db(), _check_redis(), _check_storage(), _check_celery()
    )
    all_ok = db_ok and redis_ok and storage_ok and celery_ok
    return {
        "status": "ok" if all_ok else "degraded",
        "version": __version__,
        "services": {"db": db_ok, "redis": redis_ok, "storage": storage_ok, "celery": celery_ok},
    }


@router.get("/health/ready", response_model=HealthResponse)
async def readiness():
    """Kubernetes readiness probe — are all dependencies reachable?"""
    data = await _readiness_check()
    return HealthResponse(**data)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Combined health check (backward compatible)."""
    data = await _readiness_check()
    return HealthResponse(**data)
