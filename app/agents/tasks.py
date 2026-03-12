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
    max_retries=1,
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
        # Mark instance as failed due to timeout (best-effort).
        try:
            _run_async(_mark_instances_failed(
                tenant_id,
                definition_id,
                "Agent execution timed out (soft limit reached)",
            ))
        except Exception:
            logger.exception("failed_to_mark_timeout")
        return {
            "instance_id": None,
            "status": "failed",
            "error": "soft_time_limit_exceeded",
        }
    except Exception as exc:
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


@celery_app.task(name="agents.cleanup_stale_instances")
def cleanup_stale_instances() -> dict:
    """Periodic task: mark running instances that have been stale for too long as failed.

    This task runs without tenant context (platform-level) so it uses a
    superuser connection that bypasses RLS by setting the role appropriately.
    """
    async def _run():
        from app.agents.models import AgentInstance, InstanceStatus
        from app.db.session import async_session_factory

        cutoff = datetime.now(UTC) - timedelta(hours=1)

        async with async_session_factory() as db:
            # Bypass RLS for cross-tenant cleanup.  The session factory uses
            # the application role which has FORCE RLS.  We disable it for
            # this single transaction so the UPDATE sees all tenants.
            await db.execute(text("SET LOCAL row_security = off"))

            stmt = (
                update(AgentInstance)
                .where(
                    AgentInstance.status == InstanceStatus.RUNNING,
                    AgentInstance.created_at < cutoff,
                )
                .values(
                    status=InstanceStatus.FAILED,
                    error="Stale instance: no activity for over 1 hour",
                    completed_at=datetime.now(UTC),
                )
            )
            result = await db.execute(stmt)
            await db.commit()
            return {"cleaned": result.rowcount}

    return _run_async(_run())
