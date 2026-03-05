"""Tests for quota enforcement system."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.billing.enforcement import enforce_plan_limit
from app.core.quotas import (
    DEFAULT_PLAN_LIMITS,
    QuotaMetric,
    get_current_usage,
    get_plan_limit,
    increment_usage,
)


class TestPlanLimits:
    def test_free_plan_limits(self):
        assert get_plan_limit("free", QuotaMetric.JOBS_PER_MONTH) == 100
        assert get_plan_limit("free", QuotaMetric.USERS) == 3

    def test_enterprise_unlimited(self):
        assert get_plan_limit("enterprise", QuotaMetric.JOBS_PER_MONTH) == -1
        assert get_plan_limit("enterprise", QuotaMetric.STORAGE_BYTES) == -1

    def test_unknown_plan_defaults_to_free(self):
        assert get_plan_limit("unknown_plan", QuotaMetric.JOBS_PER_MONTH) == 100

    def test_all_plans_have_all_metrics(self):
        for plan in DEFAULT_PLAN_LIMITS:
            for metric in QuotaMetric:
                assert metric in DEFAULT_PLAN_LIMITS[plan]


class TestRedisQuotaOperations:
    @pytest.mark.asyncio
    async def test_get_current_usage_returns_zero_on_error(self):
        tid = uuid4()
        with patch("app.core.quotas.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(side_effect=Exception("Redis down"))
            usage = await get_current_usage(tid, QuotaMetric.JOBS_PER_MONTH)
            assert usage == 0

    @pytest.mark.asyncio
    async def test_get_current_usage_returns_value(self):
        tid = uuid4()
        with patch("app.core.quotas.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(return_value=b"42")
            usage = await get_current_usage(tid, QuotaMetric.JOBS_PER_MONTH)
            assert usage == 42

    @pytest.mark.asyncio
    async def test_increment_usage_returns_zero_on_error(self):
        """Increment gracefully returns 0 when Redis is unavailable."""
        tid = uuid4()
        with patch("app.core.quotas.redis_pool") as mock_redis:
            mock_redis.pipeline.side_effect = Exception("Redis down")
            result = await increment_usage(tid, QuotaMetric.JOBS_PER_MONTH)
            assert result == 0


class TestEnforcePlanLimit:
    @pytest.mark.asyncio
    async def test_unlimited_plan_passes(self):
        tid = uuid4()
        await enforce_plan_limit(tid, "enterprise", QuotaMetric.JOBS_PER_MONTH)

    @pytest.mark.asyncio
    async def test_within_limit_passes(self):
        tid = uuid4()
        await enforce_plan_limit(tid, "free", QuotaMetric.JOBS_PER_MONTH, current_value=50)

    @pytest.mark.asyncio
    async def test_at_limit_raises_429(self):
        tid = uuid4()
        with pytest.raises(HTTPException) as exc_info:
            await enforce_plan_limit(tid, "free", QuotaMetric.JOBS_PER_MONTH, current_value=100)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_over_limit_raises_429(self):
        tid = uuid4()
        with pytest.raises(HTTPException) as exc_info:
            await enforce_plan_limit(tid, "free", QuotaMetric.USERS, current_value=5)
        assert exc_info.value.status_code == 429
        assert "plan_limit_exceeded" in str(exc_info.value.detail)
