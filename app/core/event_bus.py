"""Durable event bus backed by Redis Streams.

Extends the in-process domain event system with cross-process, persistent,
replayable event delivery. Events published here survive process restarts
and can be consumed by multiple independent consumer groups.

Usage:
    from app.core.event_bus import event_bus

    # Publish a durable event
    await event_bus.publish("agent.started", {"agent_id": "...", "tenant_id": "..."})

    # Consume events (typically in a worker)
    async for event in event_bus.consume("agent-worker", "agent.*"):
        await handle(event)
        await event_bus.ack("agent-worker", event.stream, event.id)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import structlog

from app.config import settings
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Stream key prefix in Redis
_STREAM_PREFIX = "events"


@dataclass
class StreamEvent:
    """A single event read from a Redis Stream."""

    id: str
    stream: str
    event_type: str
    data: dict[str, Any]
    timestamp: float = 0.0

    @property
    def age_ms(self) -> float:
        """Milliseconds since event was published."""
        if self.timestamp:
            return (time.time() - self.timestamp) * 1000
        return 0.0


class EventBus:
    """Durable event bus using Redis Streams.

    Supports:
    - Multi-stream publishing (events routed by type prefix)
    - Consumer groups for reliable delivery
    - At-least-once delivery with manual acknowledgment
    - Event replay from a specific ID or timestamp
    - Dead-letter detection via pending entry inspection
    - Configurable stream retention (MAXLEN)
    """

    def __init__(self, *, stream_prefix: str = _STREAM_PREFIX, max_len: int = 100_000):
        self._prefix = stream_prefix
        self._max_len = max_len

    def _stream_key(self, event_type: str) -> str:
        """Map event type to a Redis Stream key.

        Events are grouped into streams by their top-level category:
            'agent.started' → 'events:agent'
            'workflow.step.completed' → 'events:workflow'
        """
        category = event_type.split(".")[0]
        return f"{self._prefix}:{category}"

    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        """Publish an event to the appropriate stream.

        Returns the Redis Stream message ID (e.g. '1234567890-0').
        """
        stream_key = self._stream_key(event_type)
        payload = {
            "type": event_type,
            "data": json.dumps(data, default=str),
            "ts": str(time.time()),
        }

        try:
            msg_id = await redis_pool.xadd(
                stream_key,
                payload,
                maxlen=self._max_len,
                approximate=True,
            )
            logger.debug(
                "event_bus_published",
                event_type=event_type,
                stream=stream_key,
                msg_id=msg_id,
            )
            return msg_id
        except Exception:
            logger.error(
                "event_bus_publish_failed",
                event_type=event_type,
                stream=stream_key,
                exc_info=True,
            )
            raise

    async def ensure_group(self, group: str, stream_key: str) -> None:
        """Create a consumer group if it doesn't exist.

        Uses MKSTREAM to create the stream if it doesn't exist either.
        Starts consuming from the latest message ('$').
        """
        try:
            await redis_pool.xgroup_create(
                stream_key,
                group,
                id="$",
                mkstream=True,
            )
        except Exception as exc:
            # BUSYGROUP = group already exists — that's fine
            if "BUSYGROUP" in str(exc):
                pass
            else:
                raise

    async def consume(
        self,
        group: str,
        consumer: str,
        streams: list[str],
        *,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[StreamEvent]:
        """Read new events from one or more streams as a consumer group member.

        Returns a batch of events. The caller must ack each event after
        successful processing via `ack()`.
        """
        stream_ids = dict.fromkeys(streams, ">")

        try:
            results = await redis_pool.xreadgroup(
                group,
                consumer,
                stream_ids,
                count=count,
                block=block_ms,
            )
        except Exception:
            logger.error("event_bus_consume_failed", group=group, exc_info=True)
            return []

        events = []
        for stream_key, messages in results or []:
            # redis-py returns stream_key as str when decode_responses=True
            sk = stream_key if isinstance(stream_key, str) else stream_key.decode()
            for msg_id, fields in messages:
                mid = msg_id if isinstance(msg_id, str) else msg_id.decode()
                event_type = fields.get("type", "unknown")
                raw_data = fields.get("data", "{}")
                ts = float(fields.get("ts", 0))

                try:
                    data = json.loads(raw_data)
                except (json.JSONDecodeError, TypeError):
                    data = {"raw": raw_data}

                events.append(
                    StreamEvent(
                        id=mid,
                        stream=sk,
                        event_type=event_type,
                        data=data,
                        timestamp=ts,
                    )
                )

        return events

    async def ack(self, group: str, stream_key: str, msg_id: str) -> None:
        """Acknowledge successful processing of an event."""
        await redis_pool.xack(stream_key, group, msg_id)

    async def replay(
        self,
        stream_key: str,
        *,
        start: str = "0-0",
        end: str = "+",
        count: int = 100,
    ) -> list[StreamEvent]:
        """Replay events from a stream within a range.

        Useful for rebuilding state after agent recovery.
        """
        results = await redis_pool.xrange(stream_key, start, end, count=count)
        events = []
        for msg_id, fields in results or []:
            mid = msg_id if isinstance(msg_id, str) else msg_id.decode()
            event_type = fields.get("type", "unknown")
            raw_data = fields.get("data", "{}")
            ts = float(fields.get("ts", 0))

            try:
                data = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError):
                data = {"raw": raw_data}

            events.append(
                StreamEvent(
                    id=mid,
                    stream=stream_key,
                    event_type=event_type,
                    data=data,
                    timestamp=ts,
                )
            )
        return events

    async def pending_summary(self, group: str, stream_key: str) -> dict[str, Any]:
        """Get summary of pending (unacknowledged) events for a group.

        Returns: {count, min_id, max_id, consumers: {name: pending_count}}
        """
        try:
            info = await redis_pool.xpending(stream_key, group)
            if not info:
                return {"count": 0, "min_id": None, "max_id": None, "consumers": {}}
            return {
                "count": info["pending"],
                "min_id": info.get("min"),
                "max_id": info.get("max"),
                "consumers": {c["name"]: c["pending"] for c in info.get("consumers", [])},
            }
        except Exception:
            return {"count": 0, "min_id": None, "max_id": None, "consumers": {}}

    async def stream_info(self, stream_key: str) -> dict[str, Any]:
        """Get stream metadata (length, first/last entry ID)."""
        try:
            info = await redis_pool.xinfo_stream(stream_key)
            return {
                "length": info.get("length", 0),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
                "groups": info.get("groups", 0),
            }
        except Exception:
            return {"length": 0, "first_entry": None, "last_entry": None, "groups": 0}

    async def trim(self, stream_key: str, max_len: int | None = None) -> int:
        """Trim a stream to a maximum length. Returns number of entries removed."""
        target = max_len or self._max_len
        return await redis_pool.xtrim(stream_key, maxlen=target, approximate=True)


# Module-level singleton — wired to application config.
event_bus = EventBus(
    stream_prefix=settings.EVENT_BUS_STREAM_PREFIX,
    max_len=settings.EVENT_BUS_MAX_LEN,
)
