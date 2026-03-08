"""MCP authentication bridge.

Validates API keys against the existing ApiKey model,
resolving the authenticated tenant for each tool call.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import hash_api_key
from app.db.models import ApiKey, Tenant

logger = structlog.stdlib.get_logger()


class MCPAuthError(Exception):
    """Raised when MCP authentication fails."""

    def __init__(self, detail: str = "Invalid API key"):
        self.detail = detail
        super().__init__(detail)


async def authenticate_api_key(
    raw_key: str,
    db: AsyncSession,
) -> tuple[ApiKey, Tenant]:
    """Validate an API key and return the (ApiKey, Tenant) pair.

    Raises MCPAuthError if the key is invalid or the tenant is inactive.
    """
    key_hash = hash_api_key(raw_key)

    result = await db.execute(
        select(ApiKey)
        .options(selectinload(ApiKey.tenant))
        .where(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise MCPAuthError("Invalid API key")

    tenant = api_key.tenant
    if tenant is None or not tenant.is_active:
        raise MCPAuthError("Tenant not found or inactive")

    return api_key, tenant


def check_scopes(api_key: ApiKey, *required: str) -> None:
    """Verify the API key has all required scopes.

    Raises MCPAuthError if scopes are missing.
    """
    granted = set(api_key.scopes) if api_key.scopes else set()
    missing = set(required) - granted
    if missing:
        raise MCPAuthError(f"Insufficient API key scopes: missing {', '.join(sorted(missing))}")
