"""MCP tools for job management."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus
from app.mcp.errors import not_found_error, tool_error

logger = structlog.stdlib.get_logger()


async def job_create(
    job_type: str,
    payload: dict | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a new background job.

    Jobs run asynchronously and can be polled for status.
    Provide a job type and optional payload dict.
    """
    import json as json_mod

    # Validate job_type
    if not job_type or not job_type.strip():
        raise tool_error("Job type cannot be empty.")

    # Validate payload size to prevent abuse
    if payload:
        payload_size = len(json_mod.dumps(payload, default=str))
        if payload_size > 1_048_576:  # 1 MB
            raise tool_error(
                "Payload too large (max 1 MB).",
                hint="Reduce the payload size or upload large data as a file first.",
            )

    job = Job(
        tenant_id=tenant.id,
        type=job_type,
        status=JobStatus.PENDING,
        payload=payload or {},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    logger.info("mcp_job_created", job_id=str(job.id), type=job_type)

    return {
        "id": str(job.id),
        "type": job.type,
        "status": job.status.value,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


async def job_list(
    status: str | None = None,
    limit: int = 50,
    *,
    tenant: Any,
    db: AsyncSession,
) -> list[dict]:
    """List jobs, optionally filtered by status.

    Valid statuses: pending, processing, completed, failed.
    Returns up to `limit` jobs, newest first.
    """
    query = (
        select(Job)
        .where(Job.tenant_id == tenant.id, Job.deleted_at.is_(None))
        .order_by(Job.created_at.desc())
        .limit(min(limit, 200))
    )

    if status:
        try:
            status_enum = JobStatus(status)
        except ValueError as exc:
            raise tool_error(
                f"Invalid status: {status}",
                hint="Valid statuses: pending, processing, completed, failed, cancelled",
            ) from exc
        query = query.where(Job.status == status_enum)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return [
        {
            "id": str(j.id),
            "type": j.type,
            "status": j.status.value,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }
        for j in jobs
    ]


async def job_get(job_id: str, *, tenant: Any, db: AsyncSession) -> dict:
    """Get details of a specific job by ID.

    Returns full job details including payload, result, and error info.
    """
    try:
        uid = uuid.UUID(job_id)
    except ValueError as exc:
        raise tool_error("Invalid job ID format") from exc

    result = await db.execute(
        select(Job).where(Job.id == uid, Job.tenant_id == tenant.id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise not_found_error("Job")

    return {
        "id": str(job.id),
        "type": job.type,
        "status": job.status.value,
        "payload": job.payload,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


async def job_cancel(job_id: str, *, tenant: Any, db: AsyncSession) -> dict:
    """Cancel a pending or processing job.

    Only jobs that haven't completed can be cancelled.
    Uses row-level locking and optimistic version check.
    """
    from datetime import UTC, datetime

    try:
        uid = uuid.UUID(job_id)
    except ValueError as exc:
        raise tool_error("Invalid job ID format") from exc

    result = await db.execute(
        select(Job)
        .where(Job.id == uid, Job.tenant_id == tenant.id)
        .with_for_update()
    )
    job = result.scalar_one_or_none()

    if not job:
        raise not_found_error("Job")

    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        raise tool_error(
            f"Cannot cancel job with status '{job.status.value}'",
            hint="Only pending or processing jobs can be cancelled.",
        )

    job.status = JobStatus.CANCELLED
    job.error = "Cancelled via MCP"
    job.completed_at = datetime.now(UTC)
    job.version += 1
    await db.commit()

    return {"id": str(job.id), "status": "cancelled"}
