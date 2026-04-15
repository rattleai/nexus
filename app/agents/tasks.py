"""Celery tasks for asynchronous agent execution.

These tasks run in the worker process and handle:
    - Long-running agent executions
    - Workflow orchestration
    - Periodic cleanup of stale instances
    - Event bus consumption
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import text, update

from app.workers.celery_app import celery as celery_app

# Errors that indicate transient infrastructure issues (network, broker, DB)
# and are safe to retry.  All other errors are treated as permanent.
_TRANSIENT_ERRORS = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
)

logger = structlog.stdlib.get_logger()


async def _resolve_api_key(db, api_key_id: str) -> str:
    """Resolve an API key hash from its ID.

    This avoids passing sensitive key hashes through the Celery broker.
    """
    from sqlalchemy import select

    from app.db.models import ApiKey

    stmt = select(ApiKey.key_hash).where(
        ApiKey.id == uuid.UUID(api_key_id),
        ApiKey.active.is_(True),
    )
    result = await db.execute(stmt)
    key_hash = result.scalar_one_or_none()
    if not key_hash:
        raise ValueError(f"API key {api_key_id} not found or inactive")
    return key_hash


def _run_async(coro):
    """Run an async coroutine in a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            # Shut down async generators and pending tasks cleanly.
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            loop.close()


@celery_app.task(
    name="agents.execute_agent_run",
    bind=True,
    max_retries=2,
    soft_time_limit=540,  # 9 minutes
    time_limit=600,       # 10 minutes hard kill
)
def execute_agent_run(
    self,
    definition_id: str,
    tenant_id: str,
    input_data: dict,
    api_key_id: str,
    key_source: str = "platform",
    session_id: str | None = None,
) -> dict:
    """Execute an agent run asynchronously in a Celery worker.

    Returns a dict with the instance ID and status.
    """
    async def _run():
        from app.agents.executor import AgentExecutor
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
            # Resolve the API key by ID rather than receiving the hash
            # through the broker, which would expose it in task metadata.
            api_key = await _resolve_api_key(db, api_key_id)

            executor = AgentExecutor(db)
            instance = await executor.run(
                definition_id=uuid.UUID(definition_id),
                tenant_id=uuid.UUID(tenant_id),
                input_data=input_data,
                api_key=api_key,
                key_source=key_source,
                session_id=uuid.UUID(session_id) if session_id else None,
            )
            return {
                "instance_id": str(instance.id),
                "status": instance.status.value,
                "steps_executed": instance.steps_executed,
                "tokens_used": instance.tokens_used,
                "cost_usd": instance.cost_usd,
            }

    try:
        return _run_async(_run())
    except SoftTimeLimitExceeded:
        logger.warning(
            "agent_task_soft_timeout",
            definition_id=definition_id,
            tenant_id=tenant_id,
        )
        # Mark instance as failed due to timeout — retry status update once on failure
        for attempt in range(2):
            try:
                _run_async(_mark_instances_failed(
                    tenant_id,
                    definition_id,
                    "Agent execution timed out (soft limit reached)",
                ))
                break
            except Exception:
                if attempt == 0:
                    import time; time.sleep(0.5)
                else:
                    logger.exception("failed_to_mark_timeout_after_retry")
        return {
            "instance_id": None,
            "status": "failed",
            "error": "soft_time_limit_exceeded",
        }
    except Exception as exc:
        # Retry transient infrastructure errors with exponential backoff;
        # permanent errors (governance, validation, etc.) fail immediately.
        if isinstance(exc, _TRANSIENT_ERRORS) and self.request.retries < self.max_retries:
            logger.warning(
                "agent_task_transient_retry",
                definition_id=definition_id,
                tenant_id=tenant_id,
                attempt=self.request.retries + 1,
                error=str(exc)[:200],
            )
            raise self.retry(exc=exc, countdown=min(2 ** self.request.retries * 5, 60))

        logger.error(
            "agent_task_failed",
            definition_id=definition_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise


async def _mark_instances_failed(
    tenant_id: str,
    definition_id: str,
    error_msg: str,
) -> None:
    """Best-effort: mark running instances for this definition as failed."""
    from app.agents.models import AgentInstance, InstanceStatus
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        # Set tenant context for RLS.
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id})
        stmt = (
            update(AgentInstance)
            .where(
                AgentInstance.definition_id == uuid.UUID(definition_id),
                AgentInstance.tenant_id == uuid.UUID(tenant_id),
                AgentInstance.status == InstanceStatus.RUNNING,
            )
            .values(
                status=InstanceStatus.FAILED,
                error=error_msg,
                completed_at=datetime.now(UTC),
            )
        )
        await db.execute(stmt)
        await db.commit()


@celery_app.task(
    name="agents.execute_workflow_run",
    bind=True,
    max_retries=1,
    soft_time_limit=540,
    time_limit=600,
)
def execute_workflow_run(
    self,
    workflow_id: str,
    tenant_id: str,
    input_data: dict,
    api_key_id: str,
    key_source: str = "platform",
) -> dict:
    """Execute a workflow asynchronously in a Celery worker."""
    async def _run():
        from app.agents.orchestrator import AgentOrchestrator
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
            api_key = await _resolve_api_key(db, api_key_id)

            orchestrator = AgentOrchestrator(db)
            run = await orchestrator.run_workflow(
                workflow_id=uuid.UUID(workflow_id),
                tenant_id=uuid.UUID(tenant_id),
                input_data=input_data,
                api_key=api_key,
                key_source=key_source,
            )
            return {
                "run_id": str(run.id),
                "status": run.status.value,
                "total_steps": run.total_steps,
                "total_tokens": run.total_tokens,
                "total_cost_usd": run.total_cost_usd,
            }

    try:
        return _run_async(_run())
    except SoftTimeLimitExceeded:
        logger.warning(
            "workflow_task_soft_timeout",
            workflow_id=workflow_id,
            tenant_id=tenant_id,
        )
        return {
            "run_id": None,
            "status": "failed",
            "error": "soft_time_limit_exceeded",
        }
    except Exception as exc:
        logger.error(
            "workflow_task_failed",
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise


@celery_app.task(name="app.agents.tasks.cleanup_stale_instances")
def cleanup_stale_instances() -> dict:
    """Periodic task: three-tier stale instance detection and cleanup.

    Tier 1 — PENDING too long:  task never dispatched or worker died before pickup.
    Tier 2 — RUNNING, heartbeat stale:  heartbeat exists but has gone silent.
    Tier 3 — RUNNING, no heartbeat (legacy):  pre-migration fallback using created_at.

    Runs without tenant context (platform-level) and bypasses RLS so the
    UPDATE sees all tenants in a single sweep.
    """
    async def _run():
        from app.agents.models import AgentInstance, InstanceStatus
        from app.config import settings
        from app.db.session import admin_async_session_factory

        now = datetime.now(UTC)

        # Platform-wide sweep across all tenants — use the admin session
        # which connects as the DB superuser and bypasses RLS. Regular
        # application code must NOT use this factory.
        async with admin_async_session_factory() as db:

            # Tier 1: PENDING longer than threshold — task never started
            pending_cutoff = now - timedelta(seconds=settings.AGENT_PENDING_STALE_SECONDS)
            r1 = await db.execute(
                update(AgentInstance)
                .where(
                    AgentInstance.status == InstanceStatus.PENDING,
                    AgentInstance.created_at < pending_cutoff,
                )
                .values(
                    status=InstanceStatus.FAILED,
                    error="Stale: stuck in PENDING (task never started)",
                    completed_at=now,
                )
            )

            # Tier 2: RUNNING with heartbeat but gone silent
            heartbeat_cutoff = now - timedelta(seconds=settings.AGENT_HEARTBEAT_STALE_SECONDS)
            r2 = await db.execute(
                update(AgentInstance)
                .where(
                    AgentInstance.status == InstanceStatus.RUNNING,
                    AgentInstance.last_heartbeat_at.isnot(None),
                    AgentInstance.last_heartbeat_at < heartbeat_cutoff,
                )
                .values(
                    status=InstanceStatus.FAILED,
                    error=f"Stale: no heartbeat for >{settings.AGENT_HEARTBEAT_STALE_SECONDS}s",
                    completed_at=now,
                )
            )

            # Tier 3: RUNNING with no heartbeat (pre-migration instances), using created_at
            legacy_cutoff = now - timedelta(seconds=settings.AGENT_LEGACY_STALE_SECONDS)
            r3 = await db.execute(
                update(AgentInstance)
                .where(
                    AgentInstance.status == InstanceStatus.RUNNING,
                    AgentInstance.last_heartbeat_at.is_(None),
                    AgentInstance.created_at < legacy_cutoff,
                )
                .values(
                    status=InstanceStatus.FAILED,
                    error="Stale: no activity for >1 hour (no heartbeat)",
                    completed_at=now,
                )
            )

            await db.commit()

            counts = {
                "pending_cleaned": r1.rowcount,
                "heartbeat_stale": r2.rowcount,
                "legacy_stale": r3.rowcount,
            }
            total = sum(counts.values())
            if total > 0:
                logger.info("stale_instances_cleaned", **counts)
            return counts

    return _run_async(_run())
