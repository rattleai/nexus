"""Cursor-based pagination utilities.

Cursors are base64-encoded strings containing the sort key value.
This avoids the instability of offset-based pagination when data changes.

Usage:
    from app.core.pagination import CursorPage, paginate

    @router.get("/jobs")
    async def list_jobs(
        cursor: str | None = None,
        limit: int = Query(default=20, le=100),
        db: AsyncSession = Depends(get_db),
        tenant: Tenant = Depends(get_current_tenant),
    ) -> CursorPage[JobResponse]:
        stmt = tenant_query(select(Job), tenant).order_by(Job.created_at.desc())
        return await paginate(db, stmt, Job.created_at, limit=limit, cursor=cursor, descending=True)
"""

import base64
import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


def encode_cursor(value: Any) -> str:
    """Encode a sort-key value into an opaque cursor string."""
    if isinstance(value, datetime):
        raw = value.isoformat()
    elif isinstance(value, uuid.UUID):
        raw = str(value)
    else:
        raw = str(value)
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str, value_type: type) -> Any:
    """Decode an opaque cursor back into a sort-key value."""
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    if value_type is datetime:
        return datetime.fromisoformat(raw)
    if value_type is uuid.UUID:
        return uuid.UUID(raw)
    return raw


async def paginate(
    db: AsyncSession,
    stmt: Select,
    sort_column,
    *,
    limit: int = 20,
    cursor: str | None = None,
    descending: bool = True,
) -> CursorPage:
    """Apply cursor-based pagination to a SQLAlchemy SELECT.

    Args:
        db: Async database session
        stmt: Base SELECT statement (with filters already applied)
        sort_column: The SQLAlchemy column to sort/paginate by (e.g. Job.created_at)
        limit: Max items per page
        cursor: Opaque cursor from a previous response
        descending: Sort direction
    """
    # Determine the Python type of the sort column for cursor decoding
    col_type = sort_column.type.python_type

    if cursor:
        cursor_value = decode_cursor(cursor, col_type)
        op = sort_column < cursor_value if descending else sort_column > cursor_value
        stmt = stmt.where(op)

    order = sort_column.desc() if descending else sort_column.asc()
    stmt = stmt.order_by(order)

    # Fetch one extra to detect "has more"
    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    items = rows[:limit]

    next_cursor = None
    if has_more and items:
        last_value = getattr(items[-1], sort_column.key)
        next_cursor = encode_cursor(last_value)

    return CursorPage(items=items, next_cursor=next_cursor, has_more=has_more)
