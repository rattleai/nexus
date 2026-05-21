"""Security event dead letter queue for failed event emissions.

When security events (threat detection, A2A violations, query blocks) fail
to emit via the event bus (e.g., Redis unavailable), they are persisted here
for later replay. This prevents silent loss of security-critical events.

Integrates with:
    - app/agents/threat_detection.py for AgentThreatDetected events
    - app/agents/a2a_security.py for A2AMessageSecurityEvent
    - app/agents/db_gateway.py for AgentDBQueryBlocked events
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog

from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

_DLQ_KEY = "agent:security:dlq"
_DLQ_MAX_SIZE = 10_000


async def enqueue_dead_letter(event_type: str, data: dict[str, Any]) -> None:
    """Enqueue a failed security event for later replay."""
    entry = json.dumps(
        {
            "type": event_type,
            "data": data,
            "ts": time.time(),
        },
        default=str,
    )
    try:
        pipe = redis_pool.pipeline()
        pipe.lpush(_DLQ_KEY, entry)
        pipe.ltrim(_DLQ_KEY, 0, _DLQ_MAX_SIZE - 1)
        await pipe.execute()
    except Exception:
        # Last resort: structlog captures the event for log aggregation
        logger.error(
            "dead_letter_write_failed",
            event_type=event_type,
            data=str(data)[:500],
            exc_info=True,
        )


async def drain_dead_letters(batch_size: int = 100) -> list[dict[str, Any]]:
    """Drain dead letters for reprocessing.

    Called by periodic Celery task to replay failed security events.
    Returns list of dead letter entries.
    """
    entries: list[dict[str, Any]] = []
    try:
        raw = await redis_pool.lrange(_DLQ_KEY, 0, batch_size - 1)
        if raw:
            await redis_pool.ltrim(_DLQ_KEY, batch_size, -1)
            entries = [json.loads(r) for r in raw]
    except Exception:
        logger.error("dead_letter_drain_failed", exc_info=True)
    return entries


async def dlq_size() -> int:
    """Get the current size of the dead letter queue."""
    try:
        return await redis_pool.llen(_DLQ_KEY)
    except Exception:
        return -1
