"""Job management endpoints — scoped to the authenticated tenant."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.schemas import JobCancelResponse, JobCreate, JobResponse
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.core.url_validation import validate_webhook_url
from app.db.models import Job, JobStatus, Tenant

router = APIRouter(prefix="/jobs")
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
):
    webhook_url = str(body.webhook_url) if body.webhook_url else None
    if webhook_url:
        ssrf_error = validate_webhook_url(webhook_url)
        if ssrf_error:
            raise HTTPException(status_code=422, detail=f"Invalid webhook URL: {ssrf_error}")

    job = Job(
        tenant_id=tenant.id,
        type=body.type,
        webhook_url=webhook_url,
        payload=body.payload,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch to Celery
    from app.workers.tasks import process_job

    process_job.delay(str(job.id))
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
    result = await db.execute(select(Job).where(Job.id == job_id, Job.tenant_id == tenant.id, Job.deleted_at.is_(None)))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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

    job.status = JobStatus.FAILED
    job.error = "Cancelled by user"
    job.completed_at = datetime.now(UTC)
    await db.commit()
    logger.info("job_cancelled", job_id=str(job_id), tenant_id=str(tenant.id))
    return JobCancelResponse(id=job.id, status=job.status.value, cancelled=True)


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
    logger.info("job_soft_deleted", job_id=str(job_id), tenant_id=str(tenant.id))
