"""Event bus consumer worker.

Reads events from Redis Streams and routes them to handlers.
Can run as a standalone process or as a Celery task.

Includes Redis-based event deduplication to ensure idempotent processing.

Usage:
    # Standalone:
    python -m app.workers.event_consumer

    # As Celery task:
    celery -A app.workers.celery_app worker -Q events
"""

from __future__ import annotations

import asyncio

import structlog

from app.config import settings
from app.core.event_bus import event_bus
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Event handlers: event_type pattern → async handler function
_EVENT_HANDLERS: dict[str, list] = {}

# Deduplication: processed event IDs are stored in Redis with a TTL
_DEDUP_KEY_PREFIX = "event:processed:"
_DEDUP_TTL_SECONDS = 86400 * 2  # 2 days — covers replay windows


def on_event(event_type: str):
    """Decorator to register a handler for events matching a type pattern."""

    def decorator(func):
        _EVENT_HANDLERS.setdefault(event_type, []).append(func)
        return func

    return decorator


async def _is_duplicate(event_id: str) -> bool:
    """Check if an event has already been processed (Redis SET with NX)."""
    try:
        key = f"{_DEDUP_KEY_PREFIX}{event_id}"
        was_set = await redis_pool.set(key, "1", ex=_DEDUP_TTL_SECONDS, nx=True)
        return was_set is None  # None means key already existed
    except Exception:
        logger.warning("event_dedup_check_failed", event_id=event_id, exc_info=True)
        return False  # On Redis failure, process the event (at-least-once)


@on_event("AgentInstanceCompleted")
async def _log_agent_completion(data: dict) -> None:
    """Log agent completions for observability."""
    logger.info(
        "event_consumer_agent_completed",
        instance_id=data.get("instance_id"),
        tenant_id=data.get("tenant_id"),
        cost_usd=data.get("cost_usd"),
    )


@on_event("AgentInstanceCompleted")
async def _broadcast_instance_status_change(data: dict) -> None:
    """Push instance status change to connected WebSocket clients."""
    await _ws_broadcast_instance_update(data, "completed")


@on_event("AgentInstanceFailed")
async def _broadcast_instance_failure(data: dict) -> None:
    """Push instance failure to connected WebSocket clients."""
    await _ws_broadcast_instance_update(data, "failed")


@on_event("AgentInstanceStarted")
async def _broadcast_instance_started(data: dict) -> None:
    """Push instance start to connected WebSocket clients."""
    await _ws_broadcast_instance_update(data, "running")


@on_event("AgentInstanceStopped")
async def _broadcast_instance_stopped(data: dict) -> None:
    """Push instance stop to connected WebSocket clients."""
    await _ws_broadcast_instance_update(data, "cancelled")


async def _ws_broadcast_instance_update(data: dict, status: str) -> None:
    """Broadcast a job_update event to the tenant's WebSocket connections."""
    import uuid as _uuid

    from app.core.websocket import ws_manager

    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return
    try:
        await ws_manager.broadcast_tenant(
            _uuid.UUID(tenant_id),
            {
                "type": "job_update",
                "data": {
                    "type": "agent_instance_status_changed",
                    "instance_id": data.get("instance_id", ""),
                    "agent_id": data.get("agent_id", ""),
                    "status": status,
                    "tenant_id": tenant_id,
                },
            },
        )
    except Exception:
        logger.debug("ws_broadcast_failed", tenant_id=tenant_id, exc_info=True)


@on_event("AgentGovernanceViolation")
async def _log_governance_violation(data: dict) -> None:
    """Alert on governance violations."""
    logger.warning(
        "event_consumer_governance_violation",
        instance_id=data.get("instance_id"),
        violation_type=data.get("violation_type"),
        details=data.get("details"),
    )


@on_event("WorkflowRunCompleted")
async def _log_workflow_completion(data: dict) -> None:
    """Log workflow completions."""
    logger.info(
        "event_consumer_workflow_completed",
        run_id=data.get("run_id"),
        total_cost_usd=data.get("total_cost_usd"),
    )


async def consume_loop(
    group: str = "platform",
    consumer: str = "worker-1",
    streams: list[str] | None = None,
) -> None:
    """Main consumption loop — reads from Redis Streams and dispatches to handlers."""
    prefix = settings.EVENT_BUS_STREAM_PREFIX
    target_streams = streams or [
        f"{prefix}:AgentInstanceStarted",
        f"{prefix}:AgentInstanceCompleted",
        f"{prefix}:AgentInstanceFailed",
        f"{prefix}:AgentInstanceStopped",
        f"{prefix}:AgentGovernanceViolation",
        f"{prefix}:WorkflowRunStarted",
        f"{prefix}:WorkflowRunCompleted",
        f"{prefix}:WorkflowRunFailed",
    ]

    # Ensure consumer groups exist
    for stream in target_streams:
        await event_bus.ensure_group(group, stream)

    logger.info(
        "event_consumer_started",
        group=group,
        consumer=consumer,
        streams=target_streams,
    )

    while True:
        try:
            events = await event_bus.consume(
                group=group,
                consumer=consumer,
                streams=target_streams,
                count=10,
                block_ms=settings.EVENT_BUS_BLOCK_MS,
            )

            for event in events:
                # Deduplication: skip already-processed events
                if await _is_duplicate(event.id):
                    logger.debug("event_consumer_duplicate_skipped", event_id=event.id)
                    await event_bus.ack(group, event.stream, event.id)
                    continue

                handlers = _EVENT_HANDLERS.get(event.event_type, [])
                all_ok = True
                for handler in handlers:
                    try:
                        await handler(event.data)
                    except Exception:
                        logger.error(
                            "event_consumer_handler_failed",
                            event_type=event.event_type,
                            handler=handler.__qualname__,
                            exc_info=True,
                        )
                        all_ok = False

                # Only acknowledge if all handlers succeeded
                if all_ok:
                    await event_bus.ack(group, event.stream, event.id)
                else:
                    logger.warning(
                        "event_not_acked",
                        event_type=event.event_type,
                        event_id=event.id,
                    )

        except asyncio.CancelledError:
            logger.info("event_consumer_shutting_down")
            break
        except Exception:
            logger.error("event_consumer_error", exc_info=True)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(consume_loop())
