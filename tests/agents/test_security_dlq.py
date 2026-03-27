"""Tests for the security event dead letter queue."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.security_dlq import (
    _DLQ_KEY,
    _DLQ_MAX_SIZE,
    dlq_size,
    drain_dead_letters,
    enqueue_dead_letter,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_redis_mock() -> MagicMock:
    """Create a fully configured Redis mock for DLQ tests."""
    mock_redis = MagicMock()
    pipeline = MagicMock()
    pipeline.execute = AsyncMock(return_value=[1, True])
    mock_redis.pipeline.return_value = pipeline
    mock_redis.lrange = AsyncMock(return_value=[])
    mock_redis.ltrim = AsyncMock()
    mock_redis.llen = AsyncMock(return_value=0)
    return mock_redis


# ── TestEnqueue ──────────────────────────────────────────────────────


class TestEnqueue:
    """Validate enqueue_dead_letter adds entries to Redis."""

    @pytest.mark.asyncio
    async def test_enqueue_adds_to_redis(self):
        """enqueue_dead_letter calls lpush + ltrim via pipeline."""
        mock_redis = _make_redis_mock()

        with patch("app.agents.security_dlq.redis_pool", mock_redis):
            await enqueue_dead_letter("test_event", {"key": "value"})

        pipeline = mock_redis.pipeline.return_value
        pipeline.lpush.assert_called_once()
        # First arg to lpush is the key
        assert pipeline.lpush.call_args[0][0] == _DLQ_KEY
        # Second arg is the JSON entry
        entry = json.loads(pipeline.lpush.call_args[0][1])
        assert entry["type"] == "test_event"
        assert entry["data"] == {"key": "value"}
        assert "ts" in entry

    @pytest.mark.asyncio
    async def test_dlq_capped_at_max_size(self):
        """ltrim is called with correct bounds to cap at _DLQ_MAX_SIZE entries."""
        mock_redis = _make_redis_mock()

        with patch("app.agents.security_dlq.redis_pool", mock_redis):
            await enqueue_dead_letter("test_event", {"key": "value"})

        pipeline = mock_redis.pipeline.return_value
        pipeline.ltrim.assert_called_once_with(_DLQ_KEY, 0, _DLQ_MAX_SIZE - 1)

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_raise(self):
        """Redis failure in enqueue does not raise — logs error instead."""
        mock_redis = MagicMock()
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.pipeline.return_value = pipeline

        with patch("app.agents.security_dlq.redis_pool", mock_redis):
            # Should NOT raise
            await enqueue_dead_letter("test_event", {"key": "value"})


# ── TestDrain ────────────────────────────────────────────────────────


class TestDrain:
    """Validate drain_dead_letters returns entries and removes them from queue."""

    @pytest.mark.asyncio
    async def test_drain_returns_entries(self):
        """drain_dead_letters returns parsed JSON entries."""
        entries = [
            json.dumps({"type": "event1", "data": {"a": 1}, "ts": 1000}),
            json.dumps({"type": "event2", "data": {"b": 2}, "ts": 1001}),
        ]
        mock_redis = _make_redis_mock()
        mock_redis.lrange = AsyncMock(return_value=entries)

        with patch("app.agents.security_dlq.redis_pool", mock_redis):
            result = await drain_dead_letters(batch_size=10)

        assert len(result) == 2
        assert result[0]["type"] == "event1"
        assert result[1]["type"] == "event2"

    @pytest.mark.asyncio
    async def test_drain_removes_from_queue(self):
        """drain_dead_letters removes drained entries via ltrim."""
        entries = [json.dumps({"type": "e", "data": {}, "ts": 1})]
        mock_redis = _make_redis_mock()
        mock_redis.lrange = AsyncMock(return_value=entries)

        with patch("app.agents.security_dlq.redis_pool", mock_redis):
            await drain_dead_letters(batch_size=100)

        mock_redis.ltrim.assert_called_once_with(_DLQ_KEY, 100, -1)

    @pytest.mark.asyncio
    async def test_drain_empty_queue(self):
        """drain_dead_letters on empty queue returns empty list."""
        mock_redis = _make_redis_mock()
        mock_redis.lrange = AsyncMock(return_value=[])

        with patch("app.agents.security_dlq.redis_pool", mock_redis):
            result = await drain_dead_letters()

        assert result == []


# ── TestDLQSize ──────────────────────────────────────────────────────


class TestDLQSize:
    """Validate dlq_size returns count from Redis."""

    @pytest.mark.asyncio
    async def test_dlq_size_returns_count(self):
        """dlq_size returns the count from Redis llen."""
        mock_redis = _make_redis_mock()
        mock_redis.llen = AsyncMock(return_value=42)

        with patch("app.agents.security_dlq.redis_pool", mock_redis):
            size = await dlq_size()

        assert size == 42

    @pytest.mark.asyncio
    async def test_dlq_size_returns_negative_on_failure(self):
        """dlq_size returns -1 on Redis failure."""
        mock_redis = _make_redis_mock()
        mock_redis.llen = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("app.agents.security_dlq.redis_pool", mock_redis):
            size = await dlq_size()

        assert size == -1
