"""Tenant-scoped audit log endpoint for authenticated users."""

import ipaddress
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, get_db
from app.core.pagination import CursorPage, paginate
from app.db.models import AuditLog, Tenant
from app.db.session import set_tenant_context

router = APIRouter(prefix="/audit-logs", tags=["audit"])


def _mask_ip(ip_str: str | None) -> str | None:
    """Mask IP addresses for GDPR compliance: IPv4 → /24, IPv6 → /48."""
    if not ip_str:
        return None
    try:
        addr = ipaddress.ip_address(ip_str)
        if isinstance(addr, ipaddress.IPv4Address):
            # Zero out the last octet
            network = ipaddress.IPv4Network(f"{ip_str}/24", strict=False)
            parts = str(network.network_address).rsplit(".", 1)
            return f"{parts[0]}.xxx"
        else:
            # Zero out after /48
            network = ipaddress.IPv6Network(f"{ip_str}/48", strict=False)
            return f"{network.network_address}/48"
    except ValueError:
        return ip_str


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

    @model_validator(mode="after")
    def mask_ip_address(self) -> "AuditLogResponse":
        self.ip_address = _mask_ip(self.ip_address)
        return self


@router.get("", response_model=CursorPage[AuditLogResponse])
async def list_tenant_audit_logs(
    action: str | None = None,
    resource_type: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List audit logs for the current tenant."""
    await set_tenant_context(db, str(tenant.id))

    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant.id)

    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)

    return await paginate(
        db, stmt, AuditLog.occurred_at, limit=limit, cursor=cursor, descending=True
    )
