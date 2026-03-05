"""Shared Redis connection pool — used across the application.

Import `redis_pool` anywhere you need a Redis connection:
    from app.core.redis import redis_pool
    await redis_pool.set("key", "value")
"""

import redis.asyncio as aioredis

from app.config import settings

redis_pool: aioredis.Redis = aioredis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=20,
    socket_connect_timeout=5,
    socket_timeout=5,
)
