"""API key resolution: BYOK keys → platform keys fallback.

Resolves the correct API key for a given provider and tenant, preferring
tenant-supplied BYOK keys over platform-managed keys.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import get_platform_api_key
from app.config import settings
from app.core.cache import cached
from app.db.models.ai import AIProvider, TenantAIProviderKey

logger = structlog.stdlib.get_logger()


class NoAPIKeyError(Exception):
    """Raised when no API key is available for a provider (neither BYOK nor platform)."""

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"No API key available for provider '{provider}'")


async def resolve_api_key(
    tenant_id: uuid.UUID,
    provider: AIProvider,
    db: AsyncSession,
) -> tuple[str, str]:
    """Resolve an API key for the given provider and tenant.

    Resolution order:
    1. Tenant BYOK key (encrypted in DB, cached in Redis for 5min)
    2. Platform-managed key (from environment/settings)

    Returns:
        Tuple of (api_key, key_source) where key_source is "byok" or "platform".

    Raises:
        NoAPIKeyError: If no key is available from either source.
    """
    # 1. Try tenant BYOK key
    byok_key = await _get_tenant_byok_key(tenant_id, provider, db)
    if byok_key:
        return byok_key, "byok"

    # 2. Fall back to platform key
    platform_key = get_platform_api_key(provider)
    if platform_key:
        return platform_key, "platform"

    raise NoAPIKeyError(provider.value)


async def _get_tenant_byok_key(
    tenant_id: uuid.UUID,
    provider: AIProvider,
    db: AsyncSession,
) -> str | None:
    """Fetch and decrypt the tenant's BYOK key for the given provider.

    Returns the decrypted API key string, or None if not found/inactive.
    """
    result = await db.execute(
        select(TenantAIProviderKey).where(
            TenantAIProviderKey.tenant_id == tenant_id,
            TenantAIProviderKey.provider == provider,
            TenantAIProviderKey.is_active.is_(True),
        ).order_by(TenantAIProviderKey.created_at.desc()).limit(1)
    )
    key_record = result.scalar_one_or_none()
    if not key_record:
        return None

    api_key = key_record.get_api_key()
    if not api_key:
        logger.warning(
            "byok_key_decrypt_failed",
            tenant_id=str(tenant_id),
            provider=provider.value,
        )
        return None

    # Update last_used_at (fire-and-forget, non-blocking)
    key_record.last_used_at = datetime.now(UTC)
    try:
        await db.commit()
    except Exception:
        await db.rollback()

    return api_key


async def check_key_availability(
    tenant_id: uuid.UUID,
    provider: AIProvider,
    db: AsyncSession,
) -> tuple[bool, str]:
    """Check if an API key is available without returning the actual key.

    Returns:
        Tuple of (available, source) where source is "byok", "platform", or "none".
    """
    # Check BYOK
    result = await db.execute(
        select(TenantAIProviderKey.id).where(
            TenantAIProviderKey.tenant_id == tenant_id,
            TenantAIProviderKey.provider == provider,
            TenantAIProviderKey.is_active.is_(True),
        ).limit(1)
    )
    if result.scalar_one_or_none():
        return True, "byok"

    # Check platform
    if get_platform_api_key(provider):
        return True, "platform"

    return False, "none"
