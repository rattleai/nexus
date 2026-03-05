from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class HealthResponse(BaseModel):
    status: str
    version: str
    services: dict[str, bool]


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
    errors: list[dict] | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Offset-based pagination (legacy)."""

    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class CursorPaginatedResponse(BaseModel, Generic[T]):
    """Cursor-based pagination."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
