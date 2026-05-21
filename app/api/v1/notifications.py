"""Notification endpoints — in-app notifications for users."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_from_token, get_db
from app.db.models import Notification, User

router = APIRouter(prefix="/notifications")
logger = structlog.stdlib.get_logger()


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    message: str | None
    read: bool
    action_url: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_notification(cls, n: "Notification") -> "NotificationResponse":
        return cls(
            id=n.id,
            type=n.type,
            title=n.title,
            message=n.body,
            read=n.read_at is not None,
            action_url=n.data.get("action_url") if n.data else None,
            created_at=n.created_at,
        )


class UnreadCountResponse(BaseModel):
    count: int


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """List notifications for the current user."""
    stmt = select(Notification).where(
        Notification.user_id == user.id,
        Notification.tenant_id == user.tenant_id,
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    return [NotificationResponse.from_notification(n) for n in result.scalars().all()]


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Get unread notification count."""
    result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.tenant_id == user.tenant_id,
            Notification.read_at.is_(None),
        )
    )
    return UnreadCountResponse(count=result.scalar() or 0)


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_as_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Mark a notification as read."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
            Notification.tenant_id == user.tenant_id,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(notification)
        await db.commit()

    return NotificationResponse.from_notification(notification)


@router.post("/read-all", status_code=204)
async def mark_all_as_read(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Mark all notifications as read."""
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.tenant_id == user.tenant_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
