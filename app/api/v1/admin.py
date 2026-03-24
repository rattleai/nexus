"""Admin dashboard endpoints — system-wide management and analytics.

All endpoints require X-Admin-Key header authentication.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin_key
from app.api.rate_limit import RateLimiter
from app.core.pagination import CursorPage, paginate
from app.db.models import (
    AuditLog,
    FeatureFlag,
    Job,
    Tenant,
    TenantFeatureOverride,
    TenantMembership,
    User,
)

_admin_rate_limit = RateLimiter(max_requests=60, window=60, key_prefix="rl:admin")
router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin_key), Depends(_admin_rate_limit)])
logger = structlog.stdlib.get_logger()


# ── Schemas ──────────────────────────────────────────────


class SystemStatsResponse(BaseModel):
    total_tenants: int
    active_tenants: int
    total_users: int
    active_users: int
    total_jobs: int
    jobs_by_status: dict[str, int]
    recent_registrations_7d: int


class TenantDetailResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    is_active: bool
    user_count: int
    job_count: int
    created_at: datetime


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    actor_id: str | None
    actor_type: str
    action: str
    resource_type: str
    resource_id: str | None
    ip_address: str | None
    changes: dict | None
    occurred_at: datetime

    model_config = {"from_attributes": True}


class FeatureFlagCreate(BaseModel):
    name: str
    description: str | None = None
    enabled: bool = False
    rollout_percentage: int = 0


class FeatureFlagResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    enabled: bool
    rollout_percentage: int
    created_at: datetime

    model_config = {"from_attributes": True}


class FeatureFlagUpdate(BaseModel):
    description: str | None = None
    enabled: bool | None = None
    rollout_percentage: int | None = None


class TenantOverrideCreate(BaseModel):
    tenant_id: uuid.UUID
    enabled: bool


# ── System stats ─────────────────────────────────────────


@router.get("/stats", response_model=SystemStatsResponse)
async def get_system_stats(db: AsyncSession = Depends(get_db)):
    """Get system-wide statistics."""
    # Tenant counts
    total_tenants = (
        await db.execute(select(func.count()).select_from(Tenant).where(Tenant.deleted_at.is_(None)))
    ).scalar() or 0
    active_tenants = (
        await db.execute(
            select(func.count())
            .select_from(Tenant)
            .where(Tenant.deleted_at.is_(None), Tenant.is_active.is_(True))
        )
    ).scalar() or 0

    # User counts
    total_users = (
        await db.execute(select(func.count()).select_from(User).where(User.deleted_at.is_(None)))
    ).scalar() or 0
    active_users = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.deleted_at.is_(None), User.is_active.is_(True))
        )
    ).scalar() or 0

    # Job counts
    total_jobs = (
        await db.execute(select(func.count()).select_from(Job).where(Job.deleted_at.is_(None)))
    ).scalar() or 0

    # Jobs by status
    status_counts = await db.execute(
        select(Job.status, func.count())
        .where(Job.deleted_at.is_(None))
        .group_by(Job.status)
    )
    jobs_by_status = {row[0].value: row[1] for row in status_counts.all()}

    # Recent registrations
    week_ago = datetime.now(UTC) - timedelta(days=7)
    recent = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.created_at >= week_ago, User.deleted_at.is_(None))
        )
    ).scalar() or 0

    return SystemStatsResponse(
        total_tenants=total_tenants,
        active_tenants=active_tenants,
        total_users=total_users,
        active_users=active_users,
        total_jobs=total_jobs,
        jobs_by_status=jobs_by_status,
        recent_registrations_7d=recent,
    )


# ── Tenant management ────────────────────────────────────


@router.get("/tenants", response_model=list[TenantDetailResponse])
async def list_tenants_with_stats(
    plan: str | None = None,
    active_only: bool = True,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List tenants with usage statistics."""
    stmt = (
        select(
            Tenant,
            func.count(func.distinct(TenantMembership.user_id)).label("user_count"),
            func.count(func.distinct(Job.id)).label("job_count"),
        )
        .outerjoin(TenantMembership, TenantMembership.tenant_id == Tenant.id)
        .outerjoin(Job, (Job.tenant_id == Tenant.id) & Job.deleted_at.is_(None))
        .where(Tenant.deleted_at.is_(None))
        .group_by(Tenant.id)
        .order_by(Tenant.created_at.desc())
        .limit(limit)
    )

    if plan:
        stmt = stmt.where(Tenant.plan == plan)
    if active_only:
        stmt = stmt.where(Tenant.is_active.is_(True))

    result = await db.execute(stmt)
    rows = result.all()

    return [
        TenantDetailResponse(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            plan=tenant.plan,
            is_active=tenant.is_active,
            user_count=user_count,
            job_count=job_count,
            created_at=tenant.created_at,
        )
        for tenant, user_count, job_count in rows
    ]


# ── Audit log queries ────────────────────────────────────


@router.get("/audit-logs", response_model=CursorPage[AuditLogResponse])
async def list_audit_logs(
    tenant_id: uuid.UUID | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Query the audit log with filters."""
    stmt = select(AuditLog)

    if tenant_id:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)

    return await paginate(db, stmt, AuditLog.occurred_at, limit=limit, cursor=cursor, descending=True)


# ── Feature flag management ──────────────────────────────


@router.get("/feature-flags", response_model=list[FeatureFlagResponse])
async def list_feature_flags(db: AsyncSession = Depends(get_db)):
    """List all feature flags."""
    result = await db.execute(select(FeatureFlag).order_by(FeatureFlag.name))
    return result.scalars().all()


@router.post("/feature-flags", response_model=FeatureFlagResponse, status_code=201)
async def create_feature_flag(body: FeatureFlagCreate, db: AsyncSession = Depends(get_db)):
    """Create a new feature flag."""
    flag = FeatureFlag(
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        rollout_percentage=body.rollout_percentage,
    )
    db.add(flag)
    await db.commit()
    await db.refresh(flag)
    logger.info("feature_flag_created", name=body.name)
    return flag


@router.patch("/feature-flags/{flag_id}", response_model=FeatureFlagResponse)
async def update_feature_flag(
    flag_id: uuid.UUID,
    body: FeatureFlagUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a feature flag."""
    result = await db.execute(select(FeatureFlag).where(FeatureFlag.id == flag_id))
    flag = result.scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=404, detail="Feature flag not found")

    if body.description is not None:
        flag.description = body.description
    if body.enabled is not None:
        flag.enabled = body.enabled
    if body.rollout_percentage is not None:
        flag.rollout_percentage = body.rollout_percentage

    await db.commit()
    await db.refresh(flag)

    # Invalidate cache for all tenants
    try:
        from app.core.redis import redis_pool

        async for key in redis_pool.scan_iter(f"ff:{flag.name}:*", count=100):
            await redis_pool.delete(key)
    except Exception:
        logger.error("feature_flag_cache_invalidation_failed", flag_name=flag.name, exc_info=True)

    logger.info("feature_flag_updated", name=flag.name)
    return flag


@router.delete("/feature-flags/{flag_id}", status_code=204)
async def delete_feature_flag(flag_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a feature flag."""
    result = await db.execute(select(FeatureFlag).where(FeatureFlag.id == flag_id))
    flag = result.scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=404, detail="Feature flag not found")

    await db.delete(flag)
    await db.commit()
    logger.info("feature_flag_deleted", name=flag.name)


@router.post("/feature-flags/{flag_id}/overrides", status_code=201)
async def create_tenant_override(
    flag_id: uuid.UUID,
    body: TenantOverrideCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a per-tenant override for a feature flag."""
    result = await db.execute(select(FeatureFlag).where(FeatureFlag.id == flag_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Feature flag not found")

    override = TenantFeatureOverride(
        tenant_id=body.tenant_id,
        flag_id=flag_id,
        enabled=body.enabled,
    )
    db.add(override)
    await db.commit()

    # Invalidate cache for this tenant
    try:
        flag_result = await db.execute(select(FeatureFlag).where(FeatureFlag.id == flag_id))
        flag = flag_result.scalar_one_or_none()
        if flag:
            from app.core.redis import redis_pool

            await redis_pool.delete(f"ff:{flag.name}:{body.tenant_id}")
    except Exception:
        logger.warning("feature_flag_cache_invalidation_failed", flag_id=str(flag_id))

    return {"status": "created"}
