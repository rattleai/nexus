"""Celery tasks for asynchronous AI completions.

Allows AI requests to be processed in the background via the existing
Job queue. Results are stored on the Job record and optionally delivered
via webhook.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from app.workers.celery_app import celery_app

logger = structlog.stdlib.get_logger()


@celery_app.task(
    bind=True,
    name="ai.process_completion",
    soft_time_limit=120,
    time_limit=180,
    acks_late=True,
    max_retries=2,
    default_retry_delay=5,
)
def process_ai_completion(self, tenant_id: str, request_data: dict, job_id: str) -> None:
    """Process an AI completion asynchronously.

    Updates the Job record with the result or error when complete.
    Uses sync wrapper around async gateway since Celery workers are sync.
    """
    asyncio.run(_async_process_completion(tenant_id, request_data, job_id))


async def _async_process_completion(tenant_id: str, request_data: dict, job_id: str) -> None:
    """Async implementation of the AI completion task."""
    from app.ai.gateway import ai_gateway
    from app.ai.key_resolver import NoAPIKeyError, resolve_api_key
    from app.ai.providers import get_model_info
    from app.ai.wallet import InsufficientBalanceError, wallet_service
    from app.db.models.ai import AIUsageLog
    from app.db.models.operations import Job, JobStatus
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        # Load job
        result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
        job = result.scalar_one_or_none()
        if not job:
            logger.error("ai_task_job_not_found", job_id=job_id)
            return

        # Guard against duplicate processing (e.g. Celery retry after ack timeout)
        if job.status != JobStatus.PENDING:
            logger.warning(
                "ai_task_already_processed",
                job_id=job_id,
                status=job.status.value if hasattr(job.status, "value") else str(job.status),
            )
            return

        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now(UTC)
        await db.commit()

        tid = uuid.UUID(tenant_id)
        model = request_data["model"]
        messages = request_data["messages"]

        try:
            # Apply input guardrails — same validation as the sync endpoint
            from app.ai.guardrails import validate_input

            validate_input(messages)
            model_info = get_model_info(model)
            if not model_info:
                raise ValueError(f"Unknown model: {model}")

            # Resolve API key
            api_key, key_source = await resolve_api_key(tid, model_info.provider, db)

            # Execute completion
            completion = await ai_gateway.completion(
                tenant_id=tid,
                model=model,
                messages=messages,
                api_key=api_key,
                key_source=key_source,
                max_tokens=request_data.get("max_tokens"),
                temperature=request_data.get("temperature"),
                top_p=request_data.get("top_p"),
                fallback_models=request_data.get("fallback_models"),
                request_id=job_id,
                db=db,
            )

            # Deduct from wallet in USD
            from decimal import Decimal

            try:
                await wallet_service.deduct(
                    tid,
                    completion.billed_amount_usd,
                    provider_cost_usd=Decimal(str(completion.cost_usd)),
                    description=f"AI completion: {model}",
                    reference_id=job_id,
                    db=db,
                )
            except InsufficientBalanceError as wallet_exc:
                logger.error(
                    "ai_task_wallet_insufficient",
                    job_id=job_id,
                    billed_amount_usd=str(completion.billed_amount_usd),
                    error=str(wallet_exc),
                )
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.error = "Insufficient wallet balance for this completion. Please top up."
                await db.commit()
                return

            # Log usage
            usage_log = AIUsageLog(
                tenant_id=tid,
                provider=completion.provider,
                model=model,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                total_tokens=completion.total_tokens,
                cost_usd=completion.cost_usd,
                billed_amount_usd=completion.billed_amount_usd,
                latency_ms=completion.latency_ms,
                status="success",
                key_source=key_source,
                request_id=job_id,
            )
            db.add(usage_log)

            # Update job with result
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            job.result = {
                "id": completion.id,
                "model": completion.model,
                "content": completion.content,
                "prompt_tokens": completion.prompt_tokens,
                "completion_tokens": completion.completion_tokens,
                "total_tokens": completion.total_tokens,
                "cost_usd": completion.cost_usd,
                "billed_amount_usd": float(completion.billed_amount_usd),
                "latency_ms": completion.latency_ms,
                "key_source": completion.key_source,
                "finish_reason": completion.finish_reason,
            }
            await db.commit()

            logger.info(
                "ai_task_completed",
                job_id=job_id,
                model=model,
                tokens=completion.total_tokens,
            )

        except NoAPIKeyError as exc:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.error = f"No API key available for provider: {exc.provider}"
            await db.commit()
            logger.error("ai_task_no_api_key", job_id=job_id, provider=exc.provider)

        except Exception as exc:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.error = str(exc)[:2000]
            await db.commit()

            logger.error(
                "ai_task_failed",
                job_id=job_id,
                model=model,
                error=str(exc),
            )
