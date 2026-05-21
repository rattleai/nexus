"""Offline-first data synchronization endpoints.

Mobile clients pull changes since their last sync version and push
locally-created/modified records. The server tracks changes via the
monotonically increasing ChangeLog.id as the sync version.
"""

from __future__ import annotations

import uuid as uuid_mod
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_from_token, get_db
from app.db.models import User

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/sync", tags=["sync"])


class ChangeRecord(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    operation: str
    changed_fields: dict[str, Any] | None = None
    sync_version: int
    created_at: str


class SyncChangesResponse(BaseModel):
    changes: list[ChangeRecord]
    latest_version: int
    has_more: bool


class SyncPushItem(BaseModel):
    entity_type: str = Field(..., description="Type of entity (e.g. 'job', 'notification')")
    entity_id: str = Field(..., description="UUID of the entity")
    operation: str = Field(..., description="create or update")
    data: dict[str, Any] = Field(..., description="Entity data")
    client_version: int = Field(0, description="Client's last known sync version for this entity")


class SyncPushRequest(BaseModel):
    changes: list[SyncPushItem] = Field(..., min_length=1, max_length=100)


class SyncAccepted(BaseModel):
    entity_id: str
    server_version: int


class SyncConflict(BaseModel):
    entity_id: str
    server_version: int
    server_data: dict[str, Any]


class SyncPushResponse(BaseModel):
    accepted: list[SyncAccepted]
    conflicts: list[SyncConflict]


@router.get("/changes", response_model=SyncChangesResponse)
async def get_changes(
    since_version: int = Query(0, ge=0, description="Sync version to fetch changes since"),
    entity_types: str | None = Query(None, description="Comma-separated entity types to filter"),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
) -> SyncChangesResponse:
    """Fetch changes since a given sync version.

    Uses ChangeLog.id as the monotonically increasing sync version.
    Returns changes ordered by id, scoped to the user's tenant.
    """
    from app.db.models.mobile import ChangeLog

    stmt = select(ChangeLog).where(
        ChangeLog.tenant_id == user.tenant_id,
        ChangeLog.id > since_version,
    )

    if entity_types:
        types = [t.strip() for t in entity_types.split(",") if t.strip()]
        if types:
            stmt = stmt.where(ChangeLog.entity_type.in_(types))

    stmt = stmt.order_by(ChangeLog.id.asc()).limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    items = rows[:limit]

    # Use ChangeLog.id as the sync version
    latest_version = items[-1].id if items else since_version

    return SyncChangesResponse(
        changes=[
            ChangeRecord(
                id=str(r.id),
                entity_type=r.entity_type,
                entity_id=str(r.entity_id),
                operation=r.operation,
                changed_fields=r.changed_fields,
                sync_version=r.id,
                created_at=r.created_at.isoformat(),
            )
            for r in items
        ],
        latest_version=latest_version,
        has_more=has_more,
    )


@router.post("/push", response_model=SyncPushResponse)
async def push_changes(
    body: SyncPushRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
) -> SyncPushResponse:
    """Push locally-created or modified records to the server.

    Checks for conflicts by comparing client_version against the latest
    server ChangeLog entry for each entity. Returns conflicts with the
    server's current data so clients can resolve them.
    """
    accepted: list[SyncAccepted] = []
    conflicts: list[SyncConflict] = []

    from app.db.models.mobile import ChangeLog

    changelog_entries: list[ChangeLog] = []

    for change in body.changes:
        if change.operation not in ("create", "update"):
            raise HTTPException(status_code=400, detail=f"Invalid operation: {change.operation}")

        try:
            entity_uuid = uuid_mod.UUID(change.entity_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid entity_id: {change.entity_id}")

        if change.operation == "update":
            # Find the latest server change for this entity (using id as version)
            latest = await db.execute(
                select(ChangeLog)
                .where(
                    ChangeLog.tenant_id == user.tenant_id,
                    ChangeLog.entity_type == change.entity_type,
                    ChangeLog.entity_id == entity_uuid,
                )
                .order_by(ChangeLog.id.desc())
                .limit(1)
            )
            server_entry = latest.scalar_one_or_none()
            server_version = server_entry.id if server_entry else 0

            if server_version > change.client_version:
                # Conflict: server has newer changes — return server's changed_fields
                conflicts.append(
                    SyncConflict(
                        entity_id=change.entity_id,
                        server_version=server_version,
                        server_data=server_entry.changed_fields or {},
                    )
                )
                continue

        # Record accepted change in the ChangeLog
        changelog_entries.append(
            ChangeLog(
                tenant_id=user.tenant_id,
                entity_type=change.entity_type,
                entity_id=entity_uuid,
                operation=change.operation,
                changed_fields=change.data,
            )
        )

    # Persist all accepted ChangeLog entries
    if changelog_entries:
        for entry in changelog_entries:
            db.add(entry)
        await db.flush()
        await db.commit()

    # Build accepted list with actual server versions (ChangeLog.id)
    for entry in changelog_entries:
        accepted.append(
            SyncAccepted(
                entity_id=str(entry.entity_id),
                server_version=entry.id,
            )
        )

    logger.info(
        "sync_push",
        user_id=str(user.id),
        accepted_count=len(accepted),
        conflict_count=len(conflicts),
    )

    return SyncPushResponse(accepted=accepted, conflicts=conflicts)
