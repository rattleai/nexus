"""Tests for the Redis caching layer."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.cache import _build_key, cached, invalidate


class TestBuildKey:
    def test_format_with_kwargs(self):
        key = _build_key("tenants:{tenant_id}", (), {"tenant_id": "abc"})
        assert key == "cache:tenants:abc"

    def test_format_with_args(self):
        key = _build_key("item:{0}", ("xyz",), {})
        assert key == "cache:item:xyz"

    def test_fallback_to_hash(self):
        key = _build_key("noplaces", ("arg",), {"missing": "key"})
        assert key.startswith("cache:noplaces:")
        assert len(key) > len("cache:noplaces:")


class TestCachedDecorator:
    @pytest.fixture(autouse=True)
    def _enable_cache(self):
        with patch("app.core.cache.settings") as mock_settings:
            mock_settings.CACHE_ENABLED = True
            yield mock_settings

    @pytest.mark.asyncio
    async def test_caches_result_on_miss(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        call_count = 0

        @cached(ttl=60, key="test:func")
        async def my_func():
            nonlocal call_count
            call_count += 1
            return {"value": 42}

        with patch("app.core.cache.redis_pool", mock_redis):
            result = await my_func()

        assert result == {"value": 42}
        assert call_count == 1
        mock_redis.get.assert_called_once_with("cache:test:func")
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        assert args[0][0] == "cache:test:func"
        assert args[0][1] == 60

    @pytest.mark.asyncio
    async def test_returns_cached_on_hit(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps({"value": 42}))

        call_count = 0

        @cached(ttl=60, key="test:hit")
        async def my_func():
            nonlocal call_count
            call_count += 1
            return {"value": 99}

        with patch("app.core.cache.redis_pool", mock_redis):
            result = await my_func()

        assert result == {"value": 42}
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_redis_error(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("Redis down"))

        @cached(ttl=60, key="test:fail")
        async def my_func():
            return {"fallback": True}

        with patch("app.core.cache.redis_pool", mock_redis):
            result = await my_func()

        assert result == {"fallback": True}

    @pytest.mark.asyncio
    async def test_bypass_when_cache_disabled(self):
        call_count = 0

        @cached(ttl=60, key="test:disabled")
        async def my_func():
            nonlocal call_count
            call_count += 1
            return {"data": 1}

        with patch("app.core.cache.settings") as mock_settings:
            mock_settings.CACHE_ENABLED = False
            result = await my_func()

        assert result == {"data": 1}
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_bypass_with_cache_control_header(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps({"old": True}))

        call_count = 0

        @cached(ttl=60, key="test:bypass")
        async def my_func(request):
            nonlocal call_count
            call_count += 1
            return {"fresh": True}

        mock_request = MagicMock()
        mock_request.state.cache_bypass = True

        with patch("app.core.cache.redis_pool", mock_redis):
            result = await my_func(mock_request)

        assert result == {"fresh": True}
        assert call_count == 1


class TestInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_exact_key(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("app.core.cache.redis_pool", mock_redis):
            count = await invalidate("tenants:abc")

        assert count == 1
        mock_redis.delete.assert_called_once_with("cache:tenants:abc")

    @pytest.mark.asyncio
    async def test_invalidate_pattern(self):
        mock_redis = AsyncMock()

        async def fake_scan_iter(match=None, count=None):
            for k in ["cache:tenants:1", "cache:tenants:2"]:
                yield k

        mock_redis.scan_iter = fake_scan_iter
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("app.core.cache.redis_pool", mock_redis):
            count = await invalidate("tenants:*")

        assert count == 2

    @pytest.mark.asyncio
    async def test_invalidate_handles_redis_error(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("app.core.cache.redis_pool", mock_redis):
            count = await invalidate("tenants:abc")

        assert count == 0
