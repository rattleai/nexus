"""Tests for the durable event bus (Redis Streams)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.event_bus import EventBus, StreamEvent


@pytest.fixture
def bus():
    return EventBus(stream_prefix="test_events", max_len=1000)


class TestEventBusStreamKey:
    def test_maps_event_type_to_category(self, bus):
        assert bus._stream_key("agent.started") == "test_events:agent"
        assert bus._stream_key("workflow.step.completed") == "test_events:workflow"
        assert bus._stream_key("system") == "test_events:system"


class TestEventBusPublish:
    @pytest.mark.asyncio
    async def test_publish_calls_xadd(self, bus):
        with patch("app.core.event_bus.redis_pool") as mock_redis:
            mock_redis.xadd = AsyncMock(return_value="1234567890-0")

            msg_id = await bus.publish("agent.started", {"agent_id": "abc"})

            assert msg_id == "1234567890-0"
            mock_redis.xadd.assert_called_once()
            call_args = mock_redis.xadd.call_args
            assert call_args[0][0] == "test_events:agent"
            payload = call_args[0][1]
            assert payload["type"] == "agent.started"
            assert json.loads(payload["data"]) == {"agent_id": "abc"}

    @pytest.mark.asyncio
    async def test_publish_logs_error_on_failure(self, bus):
        with patch("app.core.event_bus.redis_pool") as mock_redis:
            mock_redis.xadd = AsyncMock(side_effect=ConnectionError("Redis down"))

            with pytest.raises(ConnectionError):
                await bus.publish("agent.started", {})


class TestEventBusConsume:
    @pytest.mark.asyncio
    async def test_consume_returns_stream_events(self, bus):
        with patch("app.core.event_bus.redis_pool") as mock_redis:
            mock_redis.xreadgroup = AsyncMock(return_value=[
                ("test_events:agent", [
                    ("1234-0", {
                        "type": "agent.started",
                        "data": '{"agent_id": "abc"}',
                        "ts": "1234567890.0",
                    }),
                ]),
            ])

            events = await bus.consume(
                "group1", "consumer1", ["test_events:agent"],
            )

            assert len(events) == 1
            assert events[0].event_type == "agent.started"
            assert events[0].data == {"agent_id": "abc"}
            assert events[0].id == "1234-0"

    @pytest.mark.asyncio
    async def test_consume_returns_empty_on_error(self, bus):
        with patch("app.core.event_bus.redis_pool") as mock_redis:
            mock_redis.xreadgroup = AsyncMock(side_effect=ConnectionError())

            events = await bus.consume("g", "c", ["test_events:agent"])
            assert events == []


class TestEventBusReplay:
    @pytest.mark.asyncio
    async def test_replay_returns_events(self, bus):
        with patch("app.core.event_bus.redis_pool") as mock_redis:
            mock_redis.xrange = AsyncMock(return_value=[
                ("1000-0", {"type": "agent.started", "data": '{"a": 1}', "ts": "1000"}),
                ("1001-0", {"type": "agent.completed", "data": '{"a": 2}', "ts": "1001"}),
            ])

            events = await bus.replay("test_events:agent", count=10)

            assert len(events) == 2
            assert events[0].event_type == "agent.started"
            assert events[1].event_type == "agent.completed"


class TestEventBusAck:
    @pytest.mark.asyncio
    async def test_ack_calls_xack(self, bus):
        with patch("app.core.event_bus.redis_pool") as mock_redis:
            mock_redis.xack = AsyncMock()

            await bus.ack("group1", "test_events:agent", "1234-0")

            mock_redis.xack.assert_called_once_with("test_events:agent", "group1", "1234-0")


class TestEventBusEnsureGroup:
    @pytest.mark.asyncio
    async def test_creates_group(self, bus):
        with patch("app.core.event_bus.redis_pool") as mock_redis:
            mock_redis.xgroup_create = AsyncMock()

            await bus.ensure_group("mygroup", "test_events:agent")

            mock_redis.xgroup_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_busygroup_error(self, bus):
        with patch("app.core.event_bus.redis_pool") as mock_redis:
            mock_redis.xgroup_create = AsyncMock(
                side_effect=Exception("BUSYGROUP Consumer Group name already exists"),
            )

            # Should not raise
            await bus.ensure_group("mygroup", "test_events:agent")
