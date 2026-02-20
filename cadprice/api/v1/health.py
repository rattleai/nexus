import logging

import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
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


async def _check_storage() -> bool:
    try:
        from cadprice.storage.s3 import get_s3_client

        client = get_s3_client()
        client.head_bucket(Bucket=settings.S3_BUCKET)
        return True
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


def _status_card(label: str, ok: bool) -> str:
    if ok:
        border = "border-green-200"
        dot = '<span class="inline-block w-2 h-2 rounded-full bg-green-500 mr-2" aria-hidden="true"></span>'
        text = "Connected"
        text_color = "text-green-700"
    else:
        border = "border-red-200"
        dot = '<span class="inline-block w-2 h-2 rounded-full bg-red-500 mr-2" aria-hidden="true"></span>'
        text = "Unavailable"
        text_color = "text-red-700"
    return (
        f'<div class="bg-surface rounded-card shadow-card border {border} p-4">'
        f'<h3 class="text-sm font-medium text-gray-500">{label}</h3>'
        f'<p class="mt-1 text-lg font-semibold {text_color} flex items-center">{dot}{text}</p>'
        f"</div>"
    )


@router.get("/health/fragment", response_class=HTMLResponse, include_in_schema=False)
async def health_fragment():
    db_ok = await _check_db()
    redis_ok = await _check_redis()
    storage_ok = await _check_storage()

    html = _status_card("Database", db_ok) + _status_card("Redis", redis_ok) + _status_card("Storage", storage_ok)
    return HTMLResponse(content=html)
