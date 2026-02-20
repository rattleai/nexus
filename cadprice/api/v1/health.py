import logging

import redis.asyncio as aioredis
from fastapi import APIRouter
from sqlalchemy import text

from cadprice.api.schemas import HealthResponse
from cadprice.config import settings
from cadprice.db.session import async_engine

logger = logging.getLogger(__name__)

router = APIRouter()


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
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        logger.warning("Redis health check failed", exc_info=True)
        return False


async def _check_minio() -> bool:
    try:
        import boto3
        from botocore.client import Config

        client = boto3.client(
            "s3",
            endpoint_url=f"{'https' if settings.MINIO_USE_SSL else 'http'}://{settings.MINIO_ENDPOINT}",
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )
        client.list_buckets()
        return True
    except Exception:
        logger.warning("MinIO health check failed", exc_info=True)
        return False


@router.get("/health", response_model=HealthResponse)
async def health_check():
    db_ok = await _check_db()
    redis_ok = await _check_redis()
    minio_ok = await _check_minio()

    all_ok = db_ok and redis_ok
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        version="0.1.0",
        services={"db": db_ok, "redis": redis_ok, "minio": minio_ok},
    )
