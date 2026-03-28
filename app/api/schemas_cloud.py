"""Pydantic request/response schemas for the cloud storage domain."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── Cloud Connection ─────────────────────────────────────


class CloudConnectionCreate(BaseModel):
    provider: str = Field(..., description="One of: google_drive, dropbox, onedrive")
    account_email: str = Field(..., min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    access_token: str = Field(..., min_length=1, description="OAuth access token (will be encrypted)")
    refresh_token: str | None = Field(default=None, description="OAuth refresh token (will be encrypted)")
    token_expires_at: datetime | None = None
    scopes: list[str] | None = None


class CloudConnectionRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    provider: str
    account_email: str
    display_name: str | None
    token_expires_at: datetime | None
    scopes: dict | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── OAuth Flow ───────────────────────────────────────────


class OAuthStartRequest(BaseModel):
    redirect_uri: str | None = Field(
        default=None,
        description="Custom redirect URI; falls back to the provider default in settings.",
    )


class OAuthStartResponse(BaseModel):
    auth_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str
    redirect_uri: str | None = None


# ── File Browsing & Import ───────────────────────────────


class CloudFileResponse(BaseModel):
    id: str
    name: str
    mime_type: str | None
    size: int | None
    path: str
    is_folder: bool
    modified_at: str | None
    thumbnail_url: str | None = None


class FileImportRequest(BaseModel):
    file_ids: list[str] = Field(..., min_length=1, max_length=50)


class FileImportResult(BaseModel):
    data_source_id: uuid.UUID
    file_id: str
    name: str
    status: str
