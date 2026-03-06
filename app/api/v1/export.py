"""Data export endpoints — GDPR right to portability and account deletion."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireRole, get_current_user_from_token, get_db
from app.core.audit import AuditAction, emit_audit_event
from app.db.models import User

router = APIRouter(prefix="/export")
logger = structlog.stdlib.get_logger()


class ExportRequest(BaseModel):
    format: str = Field(default="json", pattern=r"^(json|csv)$")


class ExportResponse(BaseModel):
    export_id: str
    status: str
    message: str


@router.post(
    "/tenant",
    response_model=ExportResponse,
    dependencies=[Depends(RequireRole("owner", "admin"))],
)
async def request_tenant_export(
    body: ExportRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Request an export of all tenant data (GDPR Article 20).

    The export is processed asynchronously via Celery. A download link
    will be sent to the requesting user's email when ready.
    """
    export_id = uuid.uuid4()

    await emit_audit_event(
        db,
        action=AuditAction.EXPORT,
        resource_type="tenant_data",
        tenant_id=user.tenant_id,
        actor_id=str(user.id),
        metadata={"format": body.format, "export_id": str(export_id)},
    )
    await db.commit()

    # Dispatch export task
    try:
        from app.workers.tasks_export import export_tenant_data

        export_tenant_data.delay(
            str(user.tenant_id),
            str(user.id),
            str(export_id),
            body.format,
        )
    except Exception:
        logger.error("export_dispatch_failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Failed to start export") from None

    logger.info("tenant_export_requested", tenant_id=str(user.tenant_id), export_id=str(export_id))
    return ExportResponse(
        export_id=str(export_id),
        status="processing",
        message="Export started. You will receive an email when it's ready.",
    )


@router.post("/account", response_model=ExportResponse)
async def request_account_export(
    body: ExportRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Request an export of personal account data (GDPR Article 20)."""
    export_id = uuid.uuid4()

    await emit_audit_event(
        db,
        action=AuditAction.EXPORT,
        resource_type="user_data",
        tenant_id=user.tenant_id,
        actor_id=str(user.id),
        metadata={"format": body.format, "export_id": str(export_id)},
    )
    await db.commit()

    try:
        from app.workers.tasks_export import export_user_data

        export_user_data.delay(str(user.id), str(export_id), body.format)
    except Exception:
        logger.error("export_dispatch_failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Failed to start export") from None

    return ExportResponse(
        export_id=str(export_id),
        status="processing",
        message="Export started. You will receive an email when it's ready.",
    )


@router.delete("/account", status_code=202)
async def request_account_deletion(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Request account deletion (GDPR Article 17 — right to erasure).

    This soft-deletes the user and anonymizes their data. The actual
    data purge happens asynchronously after a grace period.
    """
    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="user_account",
        tenant_id=user.tenant_id,
        actor_id=str(user.id),
    )

    # Soft delete — actual data purge happens via periodic task
    from datetime import UTC, datetime

    from sqlalchemy import delete, update

    from app.db.models import OAuthAccount, RefreshToken

    user.is_active = False
    user.email = f"deleted_{user.id}@anonymized.local"
    user.display_name = "Deleted User"
    user.deleted_at = datetime.now(UTC)
    user.password_hash = None

    # Revoke all refresh tokens so existing sessions can't be used
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    # Delete OAuth accounts (contain encrypted tokens)
    await db.execute(
        delete(OAuthAccount).where(OAuthAccount.user_id == user.id)
    )

    await db.commit()

    logger.info("account_deletion_requested", user_id=str(user.id))
    return {"status": "accepted", "message": "Account scheduled for deletion."}
