"""Cursor-based pagination utilities.

Cursors are base64-encoded strings containing the sort key value and a tiebreaker ID.
This avoids the instability of offset-based pagination when data changes, and the
composite cursor (sort_value, id) ensures deterministic ordering even when multiple
records share the same sort key value.

Usage:
    from app.core.pagination import CursorPage, paginate

    @router.get("/jobs")
    async def list_jobs(
        cursor: str | None = None,
        limit: int = Query(default=20, le=100),
        db: AsyncSession = Depends(get_db),
        tenant: Tenant = Depends(get_current_tenant),
    ) -> CursorPage[JobResponse]:
        stmt = tenant_query(select(Job), tenant)
        return await paginate(db, stmt, Job.created_at, limit=limit, cursor=cursor, descending=True)
"""

import base64
import json
import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


def encode_cursor(sort_value: Any, id_value: uuid.UUID) -> str:
    """Encode a composite cursor (sort_value + id) into an opaque string."""
    if isinstance(sort_value, datetime):
        raw_sort = sort_value.isoformat()
    elif isinstance(sort_value, uuid.UUID):
        raw_sort = str(sort_value)
    else:
        raw_sort = str(sort_value)
    payload = json.dumps({"s": raw_sort, "id": str(id_value)})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str, value_type: type) -> tuple[Any, uuid.UUID]:
    """Decode a composite cursor back into (sort_value, id)."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        # Support legacy single-value cursors (backwards compatibility)
        try:
            data = json.loads(raw)
            raw_sort = data["s"]
            id_val = uuid.UUID(data["id"])
        except (json.JSONDecodeError, KeyError):
            # Legacy cursor: single value without id
            if value_type is datetime:
                return datetime.fromisoformat(raw), uuid.UUID(int=0)
            if value_type is uuid.UUID:
                return uuid.UUID(raw), uuid.UUID(int=0)
            return raw, uuid.UUID(int=0)

        if value_type is datetime:
            return datetime.fromisoformat(raw_sort), id_val
        if value_type is uuid.UUID:
            return uuid.UUID(raw_sort), id_val
        return raw_sort, id_val
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor") from None


async def paginate(
    db: AsyncSession,
    stmt: Select[Any],
    sort_column: InstrumentedAttribute[Any],
    *,
    limit: int = 20,
    cursor: str | None = None,
    descending: bool = True,
) -> CursorPage[Any]:
    """Apply cursor-based pagination to a SQLAlchemy SELECT.

    Uses a composite cursor (sort_value, id) as tiebreaker to prevent
    skipped/duplicated rows when multiple records share the same sort key.

    Args:
        db: Async database session.
        stmt: Base SELECT statement (with filters already applied).
        sort_column: The SQLAlchemy column to sort/paginate by (e.g. Job.created_at).
        limit: Max items per page.
        cursor: Opaque cursor from a previous response.
        descending: Sort direction.
    """
    # Determine the Python type of the sort column for cursor decoding
    col_type = sort_column.type.python_type

    # Get the model class and its `id` column for tiebreaker
    model = sort_column.class_
    id_column = model.id

    if cursor:
        cursor_sort_value, cursor_id = decode_cursor(cursor, col_type)
        # Composite cursor: (sort_col < cursor_val) OR (sort_col == cursor_val AND id < cursor_id)
        if descending:
            op = or_(
                sort_column < cursor_sort_value,
                and_(sort_column == cursor_sort_value, id_column < cursor_id),
            )
        else:
            op = or_(
                sort_column > cursor_sort_value,
                and_(sort_column == cursor_sort_value, id_column > cursor_id),
            )
        stmt = stmt.where(op)

    if descending:
        stmt = stmt.order_by(sort_column.desc(), id_column.desc())
    else:
        stmt = stmt.order_by(sort_column.asc(), id_column.asc())

    # Fetch one extra to detect "has more"
    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    items = rows[:limit]

    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        last_sort_value = getattr(last_item, sort_column.key)
        last_id = last_item.id
        next_cursor = encode_cursor(last_sort_value, last_id)

    return CursorPage(items=items, next_cursor=next_cursor, has_more=has_more)
