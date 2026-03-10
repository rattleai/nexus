"""Event bus consumer worker.

Reads events from Redis Streams and routes them to handlers.
Can run as a standalone process or as a Celery task.

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

logger = structlog.stdlib.get_logger()

# Event handlers: event_type pattern → async handler function
_EVENT_HANDLERS: dict[str, list] = {}


def on_event(event_type: str):
    """Decorator to register a handler for events matching a type pattern."""
    def decorator(func):
        _EVENT_HANDLERS.setdefault(event_type, []).append(func)
        return func
    return decorator


@on_event("AgentInstanceCompleted")
async def _log_agent_completion(data: dict) -> None:
    """Log agent completions for observability."""
    logger.info(
        "event_consumer_agent_completed",
        instance_id=data.get("instance_id"),
        tenant_id=data.get("tenant_id"),
        cost_usd=data.get("cost_usd"),
    )


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
                handlers = _EVENT_HANDLERS.get(event.event_type, [])
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

                # Acknowledge after processing
                await event_bus.ack(group, event.stream, event.id)

        except asyncio.CancelledError:
            logger.info("event_consumer_shutting_down")
            break
        except Exception:
            logger.error("event_consumer_error", exc_info=True)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(consume_loop())
