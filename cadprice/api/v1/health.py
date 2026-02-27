import asyncio
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter
from sqlalchemy import text

from cadprice import __version__
from cadprice.api.schemas import HealthResponse
from cadprice.config import settings
from cadprice.db.session import async_engine

logger = logging.getLogger(__name__)

router = APIRouter()

_redis_pool: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_pool


async def _check_db() -> bool:
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("DB health check failed", exc_info=True)
        return False


async def _check_redis() -> bool:
    try:
        r = _get_redis()
        await r.ping()
        return True
    except Exception:
        logger.warning("Redis health check failed", exc_info=True)
        return False


def _check_storage_sync() -> bool:
    from cadprice.storage.s3 import get_s3_client

    client = get_s3_client()
    client.head_bucket(Bucket=settings.S3_BUCKET)
    return True


async def _check_storage() -> bool:
    try:
        return await asyncio.to_thread(_check_storage_sync)
    except Exception:
        logger.warning("Storage (R2) health check failed", exc_info=True)
        return False


@router.get("/health", response_model=HealthResponse)
async def health_check():
    db_ok = await _check_db()
    redis_ok = await _check_redis()
    storage_ok = await _check_storage()

    all_ok = db_ok and redis_ok
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        version=__version__,
        services={"db": db_ok, "redis": redis_ok, "storage": storage_ok},
    )
