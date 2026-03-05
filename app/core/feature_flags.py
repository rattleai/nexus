"""Feature flag system with per-tenant overrides and progressive rollout.

Usage:
    from app.core.feature_flags import is_feature_enabled, RequireFeature

    # Check programmatically
    if await is_feature_enabled("new_billing_ui", tenant_id):
        ...

    # As a FastAPI dependency
    @router.get("/beta", dependencies=[Depends(RequireFeature("beta_feature"))])
    async def beta_endpoint(): ...
"""

import hashlib
import json
import uuid

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

_FLAG_CACHE_TTL = 60  # seconds
_FLAG_CACHE_PREFIX = "ff:"


async def _get_flag_from_db(flag_name: str, db: AsyncSession):
    """Load a feature flag from the database."""
    from app.db.models import FeatureFlag

    result = await db.execute(select(FeatureFlag).where(FeatureFlag.name == flag_name))
    return result.scalar_one_or_none()


async def _get_override_from_db(flag_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession):
    """Load a tenant-specific override for a feature flag."""
    from app.db.models import TenantFeatureOverride

    result = await db.execute(
        select(TenantFeatureOverride).where(
            TenantFeatureOverride.flag_id == flag_id,
            TenantFeatureOverride.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


def _tenant_in_rollout(flag_name: str, tenant_id: uuid.UUID, percentage: int) -> bool:
    """Deterministic rollout check using hash of flag name + tenant ID."""
    if percentage <= 0:
        return False
    if percentage >= 100:
        return True
    h = hashlib.sha256(f"{flag_name}:{tenant_id}".encode()).hexdigest()
    bucket = int(h[:8], 16) % 100
    return bucket < percentage


async def is_feature_enabled(
    flag_name: str,
    tenant_id: uuid.UUID,
    db: AsyncSession | None = None,
) -> bool:
    """Check if a feature flag is enabled for a given tenant.

    Resolution order:
    1. Tenant-specific override (if exists)
    2. Percentage rollout (deterministic by tenant)
    3. Global default
    """
    # Try cache first
    cache_key = f"{_FLAG_CACHE_PREFIX}{flag_name}:{tenant_id}"
    try:
        cached = await redis_pool.get(cache_key)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        pass

    if db is None:
        # Without a DB session, return False (fail-closed)
        return False

    flag = await _get_flag_from_db(flag_name, db)
    if flag is None:
        return False

    # Check tenant override
    override = await _get_override_from_db(flag.id, tenant_id, db)
    if override is not None:
        result = override.enabled
    elif flag.rollout_percentage > 0:
        result = _tenant_in_rollout(flag_name, tenant_id, flag.rollout_percentage)
    else:
        result = flag.enabled

    # Cache the result
    import contextlib

    with contextlib.suppress(Exception):
        await redis_pool.setex(cache_key, _FLAG_CACHE_TTL, json.dumps(result))

    return result


def require_feature(flag_name: str):
    """Create a FastAPI dependency that gates an endpoint behind a feature flag.

    Usage:
        @router.get("/beta", dependencies=[Depends(require_feature("beta_feature"))])
        async def beta(): ...
    """

    async def _check(request) -> None:
        tenant = getattr(request.state, "tenant", None)
        if tenant is None:
            return  # No tenant context — skip flag check

        from app.api.deps import get_db

        async for db in get_db():
            enabled = await is_feature_enabled(flag_name, tenant.id, db)
            if not enabled:
                raise HTTPException(status_code=404, detail="Not found")
            break

    return _check
