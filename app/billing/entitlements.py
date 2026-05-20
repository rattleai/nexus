"""Entitlements engine — decouples feature access from billing logic.

Evaluates what a tenant can do based on their plan, add-ons, and usage.
Separated from Stripe billing so entitlements can be evaluated in
microseconds without external API calls.

Usage:
    from app.billing.entitlements import entitlements

    can_use = await entitlements.check(tenant_id, "agents:execute", db=db)
    limits = await entitlements.get_limits(tenant_id, db=db)
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.stdlib.get_logger()

# Plan-based entitlements matrix
# Each plan defines: features (bool), limits (int), and capabilities
_PLAN_ENTITLEMENTS: dict[str, dict[str, Any]] = {
    "free": {
        "features": {
            "ai:completion": True,
            "agents:execute": False,
            "agents:workflow": False,
            "storage:upload": True,
            "webhooks:create": True,
            "mcp:access": False,
            "api_keys:create": True,
            "team:invite": True,
            "billing:usage_export": False,
            "sso:enabled": False,
            "audit:extended": False,
        },
        "limits": {
            "ai_requests_per_day": 100,
            "agent_runs_per_day": 0,
            "storage_bytes": 100 * 1024 * 1024,  # 100 MB
            "team_members": 3,
            "api_keys": 2,
            "webhook_endpoints": 2,
            "max_file_size_bytes": 10 * 1024 * 1024,  # 10 MB
        },
    },
    "starter": {
        "features": {
            "ai:completion": True,
            "agents:execute": True,
            "agents:workflow": False,
            "storage:upload": True,
            "webhooks:create": True,
            "mcp:access": True,
            "api_keys:create": True,
            "team:invite": True,
            "billing:usage_export": True,
            "sso:enabled": False,
            "audit:extended": False,
        },
        "limits": {
            "ai_requests_per_day": 1_000,
            "agent_runs_per_day": 50,
            "storage_bytes": 1 * 1024 * 1024 * 1024,  # 1 GB
            "team_members": 10,
            "api_keys": 10,
            "webhook_endpoints": 10,
            "max_file_size_bytes": 50 * 1024 * 1024,  # 50 MB
        },
    },
    "pro": {
        "features": {
            "ai:completion": True,
            "agents:execute": True,
            "agents:workflow": True,
            "storage:upload": True,
            "webhooks:create": True,
            "mcp:access": True,
            "api_keys:create": True,
            "team:invite": True,
            "billing:usage_export": True,
            "sso:enabled": True,
            "audit:extended": True,
        },
        "limits": {
            "ai_requests_per_day": 10_000,
            "agent_runs_per_day": 500,
            "storage_bytes": 10 * 1024 * 1024 * 1024,  # 10 GB
            "team_members": 50,
            "api_keys": 50,
            "webhook_endpoints": 50,
            "max_file_size_bytes": 200 * 1024 * 1024,  # 200 MB
        },
    },
    "enterprise": {
        "features": {
            "ai:completion": True,
            "agents:execute": True,
            "agents:workflow": True,
            "storage:upload": True,
            "webhooks:create": True,
            "mcp:access": True,
            "api_keys:create": True,
            "team:invite": True,
            "billing:usage_export": True,
            "sso:enabled": True,
            "audit:extended": True,
        },
        "limits": {
            "ai_requests_per_day": -1,  # unlimited
            "agent_runs_per_day": -1,
            "storage_bytes": -1,
            "team_members": -1,
            "api_keys": -1,
            "webhook_endpoints": -1,
            "max_file_size_bytes": 500 * 1024 * 1024,  # 500 MB
        },
    },
}


class EntitlementDenied(Exception):
    """Raised when an entitlement check fails."""

    def __init__(self, feature: str, plan: str, message: str = ""):
        self.feature = feature
        self.plan = plan
        super().__init__(message or f"Feature '{feature}' is not available on the '{plan}' plan")


class EntitlementsEngine:
    """Evaluates tenant entitlements based on plan and usage."""

    def get_plan_entitlements(self, plan: str) -> dict[str, Any]:
        """Get the full entitlements for a plan."""
        return _PLAN_ENTITLEMENTS.get(plan, _PLAN_ENTITLEMENTS["free"])

    async def check_feature(
        self,
        tenant_id: uuid.UUID,
        feature: str,
        *,
        db: AsyncSession,
    ) -> bool:
        """Check if a tenant has access to a specific feature."""
        plan = await self._get_tenant_plan(tenant_id, db)
        entitlements = self.get_plan_entitlements(plan)
        return entitlements.get("features", {}).get(feature, False)

    async def require_feature(
        self,
        tenant_id: uuid.UUID,
        feature: str,
        *,
        db: AsyncSession,
    ) -> None:
        """Require a feature — raises EntitlementDenied if not available."""
        plan = await self._get_tenant_plan(tenant_id, db)
        entitlements = self.get_plan_entitlements(plan)
        if not entitlements.get("features", {}).get(feature, False):
            raise EntitlementDenied(feature, plan)

    async def get_limit(
        self,
        tenant_id: uuid.UUID,
        limit_name: str,
        *,
        db: AsyncSession,
    ) -> int:
        """Get a specific limit value for a tenant. Returns -1 for unlimited."""
        plan = await self._get_tenant_plan(tenant_id, db)
        entitlements = self.get_plan_entitlements(plan)
        return entitlements.get("limits", {}).get(limit_name, 0)

    async def check_limit(
        self,
        tenant_id: uuid.UUID,
        limit_name: str,
        current_usage: int,
        *,
        db: AsyncSession,
    ) -> bool:
        """Check if current usage is within the limit. Returns True if allowed."""
        limit = await self.get_limit(tenant_id, limit_name, db=db)
        if limit == -1:
            return True  # unlimited
        return current_usage < limit

    async def get_all_entitlements(
        self,
        tenant_id: uuid.UUID,
        *,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Get complete entitlements for a tenant (features + limits)."""
        plan = await self._get_tenant_plan(tenant_id, db)
        entitlements = self.get_plan_entitlements(plan)
        return {"plan": plan, **entitlements}

    async def _get_tenant_plan(self, tenant_id: uuid.UUID, db: AsyncSession) -> str:
        """Resolve the tenant's current plan."""
        from app.db.models import Tenant

        tenant = await db.get(Tenant, tenant_id)
        if not tenant:
            return "free"
        return tenant.plan or "free"


# Module singleton
entitlements = EntitlementsEngine()
