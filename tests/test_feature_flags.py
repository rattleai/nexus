"""Tests for feature flag system."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.feature_flags import is_feature_enabled


class TestFeatureFlags:
    @pytest.mark.asyncio
    async def test_feature_not_found_returns_false(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.core.feature_flags.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.setex = AsyncMock()

            result = await is_feature_enabled("nonexistent_flag", uuid4(), mock_db)
            assert result is False

    @pytest.mark.asyncio
    async def test_feature_disabled_returns_false(self):
        mock_db = AsyncMock()
        mock_flag = MagicMock()
        mock_flag.enabled = False
        mock_flag.rollout_percentage = 0

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_flag
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.core.feature_flags.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.setex = AsyncMock()

            result = await is_feature_enabled("test_flag", uuid4(), mock_db)
            assert result is False

    @pytest.mark.asyncio
    async def test_feature_enabled_globally(self):
        mock_db = AsyncMock()
        mock_flag = MagicMock()
        mock_flag.enabled = True
        mock_flag.rollout_percentage = 100

        # First call returns no override, second returns the flag
        mock_result_no_override = MagicMock()
        mock_result_no_override.scalar_one_or_none.return_value = None
        mock_result_flag = MagicMock()
        mock_result_flag.scalar_one_or_none.return_value = mock_flag

        mock_db.execute = AsyncMock(side_effect=[mock_result_flag, mock_result_no_override])

        with patch("app.core.feature_flags.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.setex = AsyncMock()

            result = await is_feature_enabled("test_flag", uuid4(), mock_db)
            assert result is True

    @pytest.mark.asyncio
    async def test_cached_result_used(self):
        """When Redis has a cached result, DB is not queried."""
        mock_db = AsyncMock()

        with patch("app.core.feature_flags.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(return_value=b"1")

            result = await is_feature_enabled("cached_flag", uuid4(), mock_db)
            assert result  # Truthy (Redis returns bytes, cached value is 1)
            mock_db.execute.assert_not_called()
