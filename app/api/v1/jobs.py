"""Job management endpoints — scoped to the authenticated tenant."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.api.schemas import JobCancelResponse, JobCreate, JobResponse
from app.billing.enforcement import enforce_plan_limit, get_effective_plan
from app.core.cache import cached, invalidate
from app.core.pagination import CursorPage, paginate
from app.core.quotas import QuotaMetric, decrement_usage, increment_usage
from app.core.tenant import tenant_query
from app.core.url_validation import validate_webhook_url_async
from app.db.models import Job, JobStatus, Tenant

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/jobs", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()


class JobStatusFilter(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@router.post(
    "",
    response_model=JobResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("jobs:write"))],
)
async def create_job(
    body: JobCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
):
    # Enforce plan quota for job creation
    plan = await get_effective_plan(tenant.id, db)
    await enforce_plan_limit(tenant.id, plan, QuotaMetric.JOBS_PER_MONTH)

    webhook_url = str(body.webhook_url) if body.webhook_url else None
    if webhook_url:
        ssrf_error = await validate_webhook_url_async(webhook_url)
        if ssrf_error:
            raise HTTPException(status_code=422, detail=f"Invalid webhook URL: {ssrf_error}")

    # Idempotency: if a key is provided, check for existing job with same input_hash
    input_hash = None
    if x_idempotency_key:
        import hashlib
        input_hash = hashlib.sha256(f"{tenant.id}:{x_idempotency_key}".encode()).hexdigest()
        existing = await db.execute(
            select(Job).where(Job.tenant_id == tenant.id, Job.input_hash == input_hash, Job.deleted_at.is_(None))
        )
        existing_job = existing.scalar_one_or_none()
        if existing_job:
            return existing_job

    job = Job(
        tenant_id=tenant.id,
        type=body.type,
        webhook_url=webhook_url,
        payload=body.payload,
        status=JobStatus.PENDING,
        input_hash=input_hash,
    )
    db.add(job)

    # Track usage before commit so failures roll back together.
    # Redis increment happens first; if DB commit fails, we decrement to compensate.
    await increment_usage(tenant.id, QuotaMetric.JOBS_PER_MONTH)
    try:
        await db.commit()
    except Exception:
        await decrement_usage(tenant.id, QuotaMetric.JOBS_PER_MONTH)
        raise
    await db.refresh(job)

    # Dispatch to Celery — if the broker is unreachable, log the error but
    # still return the job (it stays PENDING and will be picked up by the
    # stale-processing cleanup or can be retried manually).
    try:
        from app.workers.tasks import process_job

        process_job.delay(str(job.id))
    except Exception:
        logger.error("celery_dispatch_failed", job_id=str(job.id), exc_info=True)

    logger.info("job_created", job_id=str(job.id), type=body.type, tenant_id=str(tenant.id))
    return job


@router.get(
    "",
    response_model=CursorPage[JobResponse],
    dependencies=[Depends(RequireScopes("jobs:read"))],
)
async def list_jobs(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    status: JobStatusFilter | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = tenant_query(select(Job).where(Job.deleted_at.is_(None)), tenant)
    if status:
        stmt = stmt.where(Job.status == status.value)
    return await paginate(db, stmt, Job.created_at, limit=limit, cursor=cursor, descending=True)


@cached(group="job_status", key="jobs:{job_id}")
async def _get_job_cached(job_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession) -> dict | None:
    result = await db.execute(select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id, Job.deleted_at.is_(None)))
    job = result.scalar_one_or_none()
    if not job:
        return None
    return JobResponse.model_validate(job).model_dump(mode="json")


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    dependencies=[Depends(RequireScopes("jobs:read"))],
)
async def get_job(
    job_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    data = await _get_job_cached(job_id, tenant.id, db)
    if not data:
        raise HTTPException(status_code=404, detail="Job not found")
    return data


@router.post(
    "/{job_id}/cancel",
    response_model=JobCancelResponse,
    dependencies=[Depends(RequireScopes("jobs:write"))],
)
async def cancel_job(
    job_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id, Job.tenant_id == tenant.id, Job.deleted_at.is_(None)))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in (JobStatus.PENDING, JobStatus.PROCESSING):
        return JobCancelResponse(id=job.id, status=job.status.value, cancelled=False)

    # Use optimistic locking to prevent race with worker completion
    from sqlalchemy import update
    cancel_result = await db.execute(
        update(Job)
        .where(Job.id == job_id, Job.version == job.version)
        .values(
            status=JobStatus.FAILED,
            error="Cancelled by user",
            completed_at=datetime.now(UTC),
            version=job.version + 1,
        )
    )
    if cancel_result.rowcount == 0:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Job state changed concurrently, please retry")

    await db.commit()
    await invalidate(f"jobs:{job_id}")
    logger.info("job_cancelled", job_id=str(job_id), tenant_id=str(tenant.id))
    return JobCancelResponse(id=job.id, status=JobStatus.FAILED.value, cancelled=True)


@router.delete(
    "/{job_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("jobs:write"))],
)
async def delete_job(
    job_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id, Job.tenant_id == tenant.id, Job.deleted_at.is_(None)))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.deleted_at = datetime.now(UTC)
    await db.commit()
    await invalidate(f"jobs:{job_id}")
    logger.info("job_soft_deleted", job_id=str(job_id), tenant_id=str(tenant.id))
