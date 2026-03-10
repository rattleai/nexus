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
from sqlalchemy import select, update

from app.workers.celery_app import celery as celery_app

logger = structlog.stdlib.get_logger()


def _run_async(coro):
    """Run an async coroutine in a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
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
    api_key: str,
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
    except Exception as exc:
        logger.error(
            "agent_task_failed",
            definition_id=definition_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise


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
    api_key: str,
    key_source: str = "platform",
) -> dict:
    """Execute a workflow asynchronously in a Celery worker."""
    async def _run():
        from app.agents.orchestrator import AgentOrchestrator
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
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
    """Periodic task: mark running instances that have been stale for too long as failed."""
    async def _run():
        from app.agents.models import AgentInstance, InstanceStatus
        from app.db.session import async_session_factory

        cutoff = datetime.now(UTC) - timedelta(hours=1)

        async with async_session_factory() as db:
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
