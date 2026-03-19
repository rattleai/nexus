"""Tenant-scoped audit log endpoint for authenticated users."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, get_db
from app.core.pagination import CursorPage, paginate
from app.db.models import AuditLog, Tenant
from app.db.session import set_tenant_context

router = APIRouter(prefix="/audit-logs", tags=["audit"])


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
