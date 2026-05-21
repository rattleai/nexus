"""P1.5: Rate limiter (token bucket + provider backoff)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors.rate_limiter import RateLimited, connector_rate_limiter


class _FakeRedis:
    def __init__(self) -> None:
        self._state: dict[str, dict[str, str]] = {}
        self._ttl: dict[str, int] = {}

    def pipeline(self, transaction=True):
        outer = self

        class _Pipe:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def hgetall(self, key):
                self._last = key
                return outer._state.get(key, {})

            async def execute(self):
                return [outer._state.get(self._last, {})]

        return _Pipe()

    async def hset(self, key, mapping):
        self._state[key] = mapping

    async def expire(self, key, ttl):
        self._ttl[key] = ttl

    async def setex(self, key, ttl, value):
        self._state[key] = {"value": value}
        self._ttl[key] = ttl

    async def ttl(self, key):
        return self._ttl.get(key, -2)


@pytest.mark.asyncio
async def test_allows_calls_under_burst_limit():
    fake = _FakeRedis()
    with patch("app.connectors.rate_limiter.redis_pool", fake):
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        for _ in range(5):
            await connector_rate_limiter.check_and_consume(
                tenant_id=tenant_id,
                connector_slug="slack",
                actor_user_id=user_id,
            )


@pytest.mark.asyncio
async def test_provider_backoff_blocks_all_users():
    fake = _FakeRedis()
    with patch("app.connectors.rate_limiter.redis_pool", fake):
        tenant_id = uuid.uuid4()

        await connector_rate_limiter.apply_provider_backoff(
            tenant_id=tenant_id,
            connector_slug="slack",
            retry_after=30,
        )
        with pytest.raises(RateLimited) as ctx:
            await connector_rate_limiter.check_and_consume(
                tenant_id=tenant_id,
                connector_slug="slack",
                actor_user_id=uuid.uuid4(),
            )
        assert ctx.value.retry_after >= 1


@pytest.mark.asyncio
async def test_fail_open_when_redis_down():
    broken = AsyncMock()
    broken.pipeline.side_effect = Exception("redis is down")

    with patch("app.connectors.rate_limiter.redis_pool", broken):
        # Should not raise — fail-open is the documented behavior
        await connector_rate_limiter.check_and_consume(
            tenant_id=uuid.uuid4(),
            connector_slug="slack",
            actor_user_id=None,
        )
