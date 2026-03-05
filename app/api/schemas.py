import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ── Health ────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    version: str
    services: dict[str, bool]


# ── Error ─────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
    errors: list[dict] | None = None


# ── Pagination ────────────────────────────────────────────


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


# ── Tenant ────────────────────────────────────────────────


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    plan: str = Field(default="free", max_length=50)
    settings: dict | None = None


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    plan: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None
    settings: dict | None = None


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    is_active: bool
    settings: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── API Key ───────────────────────────────────────────────


class ApiKeyCreate(BaseModel):
    name: str = Field(default="default", max_length=255)
    rate_limit: int | None = Field(default=100, ge=1, le=10000)
    scopes: list[str] | None = None


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    rate_limit: int | None
    scopes: list | None
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only on creation — includes the raw key (shown once)."""

    raw_key: str


class ApiKeyRevokeResponse(BaseModel):
    id: uuid.UUID
    revoked: bool = True


# ── Job ───────────────────────────────────────────────────


class JobCreate(BaseModel):
    type: str = Field(..., min_length=1, max_length=50)
    webhook_url: str | None = Field(default=None, max_length=2048)
    payload: dict | None = None


class JobResponse(BaseModel):
    id: uuid.UUID
    type: str
    status: str
    webhook_url: str | None
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    result: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobCancelResponse(BaseModel):
    id: uuid.UUID
    status: str
    cancelled: bool


# ── File upload ───────────────────────────────────────────


class FileUploadResponse(BaseModel):
    key: str
    size: int
    content_type: str


class FilePresignedUrlResponse(BaseModel):
    url: str
    expires_in: int
