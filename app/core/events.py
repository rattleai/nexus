"""Domain event system for decoupled cross-cutting concerns.

Events are dispatched in-process to registered handlers. For cross-process
delivery, handlers can dispatch Celery tasks.

Usage:
    from app.core.events import emit, DomainEvent

    @dataclass
    class JobCompleted(DomainEvent):
        job_id: str
        tenant_id: str
        job_type: str

    # Register a handler
    @on(JobCompleted)
    async def handle_job_completed(event: JobCompleted):
        await send_notification(...)

    # Emit an event
    await emit(JobCompleted(job_id="...", tenant_id="...", job_type="..."))
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.stdlib.get_logger()

# Type alias for async event handlers
EventHandler = Callable[..., Coroutine[Any, Any, None]]

# Global registry: event class -> list of handlers
_handlers: dict[type, list[EventHandler]] = defaultdict(list)


@dataclass
class DomainEvent:
    """Base class for all domain events."""

    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def event_name(self) -> str:
        return self.__class__.__name__


@dataclass
class TenantCreated(DomainEvent):
    tenant_id: str = ""
    tenant_slug: str = ""
    actor_id: str = ""


@dataclass
class TenantUpdated(DomainEvent):
    tenant_id: str = ""
    changes: dict = field(default_factory=dict)
    actor_id: str = ""


@dataclass
class TenantDeleted(DomainEvent):
    tenant_id: str = ""
    tenant_slug: str = ""
    actor_id: str = ""


@dataclass
class UserRegistered(DomainEvent):
    user_id: str = ""
    email: str = ""
    tenant_id: str = ""


@dataclass
class UserLoggedIn(DomainEvent):
    user_id: str = ""
    ip_address: str = ""


@dataclass
class JobCreated(DomainEvent):
    job_id: str = ""
    tenant_id: str = ""
    job_type: str = ""


@dataclass
class JobCompleted(DomainEvent):
    job_id: str = ""
    tenant_id: str = ""
    job_type: str = ""
    result: dict = field(default_factory=dict)


@dataclass
class JobFailed(DomainEvent):
    job_id: str = ""
    tenant_id: str = ""
    job_type: str = ""
    error: str = ""


@dataclass
class FileUploaded(DomainEvent):
    tenant_id: str = ""
    file_key: str = ""
    size: int = 0


@dataclass
class FileDeleted(DomainEvent):
    tenant_id: str = ""
    file_key: str = ""


@dataclass
class ApiKeyCreated(DomainEvent):
    tenant_id: str = ""
    key_id: str = ""
    actor_id: str = ""


@dataclass
class ApiKeyRevoked(DomainEvent):
    tenant_id: str = ""
    key_id: str = ""
    actor_id: str = ""


@dataclass
class InvitationSent(DomainEvent):
    tenant_id: str = ""
    email: str = ""
    role: str = ""
    invited_by: str = ""
    accept_url: str = ""  # pre-constructed URL — never store raw tokens in events


@dataclass
class InvitationAccepted(DomainEvent):
    tenant_id: str = ""
    user_id: str = ""
    email: str = ""


@dataclass
class MemberRemoved(DomainEvent):
    tenant_id: str = ""
    user_id: str = ""
    actor_id: str = ""


@dataclass
class WebhookEndpointCreated(DomainEvent):
    tenant_id: str = ""
    endpoint_id: str = ""


@dataclass
class SubscriptionChanged(DomainEvent):
    tenant_id: str = ""
    old_plan: str = ""
    new_plan: str = ""


@dataclass
class DataExportRequested(DomainEvent):
    tenant_id: str = ""
    user_id: str = ""
    export_type: str = ""


@dataclass
class ExportCompleted(DomainEvent):
    tenant_id: str = ""
    user_id: str = ""
    export_id: str = ""
    download_url: str = ""


@dataclass
class PaymentReceived(DomainEvent):
    tenant_id: str = ""
    amount_cents: int = 0
    plan_name: str = ""


@dataclass
class PaymentFailed(DomainEvent):
    tenant_id: str = ""
    plan_name: str = ""


def on(event_type: type) -> Callable:
    """Decorator to register an async handler for a domain event type."""

    def decorator(func: EventHandler) -> EventHandler:
        _handlers[event_type].append(func)
        return func

    return decorator


async def emit(event: DomainEvent, *, durable: bool = False) -> None:
    """Dispatch a domain event to all registered handlers.

    Handlers run concurrently. Failures in individual handlers are logged
    but do not prevent other handlers from running.

    If durable=True, the event is also published to the Redis Streams event
    bus for cross-process delivery and persistence.
    """
    event_type = type(event)
    handlers = _handlers.get(event_type, [])

    if not handlers and not durable:
        logger.debug("event_no_handlers", event_name=event.event_name)
        return

    logger.info("event_emitting", event_name=event.event_name, handler_count=len(handlers), durable=durable)

    tasks = []
    for handler in handlers:
        tasks.append(_safe_call(handler, event))

    # Publish to durable event bus if requested
    if durable:
        tasks.append(_publish_durable(event))

    await asyncio.gather(*tasks)


async def _publish_durable(event: DomainEvent) -> None:
    """Publish event to the Redis Streams event bus."""
    try:
        from app.core.event_bus import event_bus
        from dataclasses import asdict

        data = asdict(event)
        # Convert datetime to ISO string for JSON serialization
        data.pop("occurred_at", None)
        data["occurred_at"] = event.occurred_at.isoformat()

        await event_bus.publish(event.event_name, data)
    except Exception:
        logger.error(
            "event_durable_publish_failed",
            event_name=event.event_name,
            exc_info=True,
        )


async def _safe_call(handler: EventHandler, event: DomainEvent) -> None:
    """Call a handler, catching and logging any exceptions."""
    try:
        await handler(event)
    except Exception:
        logger.error(
            "event_handler_failed",
            event_name=event.event_name,
            handler=handler.__qualname__,
            exc_info=True,
        )


def clear_handlers() -> None:
    """Clear all registered handlers. Useful for testing."""
    _handlers.clear()
