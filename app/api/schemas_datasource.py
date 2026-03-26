"""Pydantic request/response schemas for the data source domain."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import json

from pydantic import BaseModel, Field, field_validator


_MAX_METADATA_BYTES = 65536  # 64KB


def _validate_metadata_size(v: dict[str, Any] | None) -> dict[str, Any] | None:
    if v is not None:
        size = len(json.dumps(v))
        if size > _MAX_METADATA_BYTES:
            raise ValueError(f"metadata exceeds maximum size of 64KB (got {size} bytes)")
    return v


# ── Data Source ──────────────────────────────────────────


class DataSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_type: str = Field(..., description="One of: upload, cloud_drive, url, paste")
    filename: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=100)
    file_size: int | None = Field(default=None, ge=0)
    url: str | None = Field(default=None, max_length=2048)
    cloud_provider: str | None = Field(default=None, description="One of: google_drive, dropbox, onedrive")
    cloud_connection_id: uuid.UUID | None = None
    cloud_file_id: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, description="Pasted text content (for source_type=paste)")
    metadata: dict[str, Any] | None = None

    _validate_metadata = field_validator("metadata")(_validate_metadata_size)


class DataSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: dict[str, Any] | None = None

    _validate_metadata = field_validator("metadata")(_validate_metadata_size)


class DataSourceRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    source_type: str
    status: str
    file_key: str | None
    filename: str | None
    mime_type: str | None
    file_size: int | None
    url: str | None
    cloud_provider: str | None
    cloud_connection_id: uuid.UUID | None
    cloud_file_id: str | None
    extraction_error: str | None
    chunk_count: int
    metadata: dict | None = Field(None, alias="metadata_")
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None

    model_config = {"from_attributes": True, "populate_by_name": True}


class DataSourceList(BaseModel):
    items: list[DataSourceRead]
    total: int
    page: int
    page_size: int

    model_config = {"from_attributes": True}


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


# ── Data Source Chunk ────────────────────────────────────


class DataSourceChunkRead(BaseModel):
    id: uuid.UUID
    data_source_id: uuid.UUID
    chunk_index: int
    content: str
    embedding_model: str | None
    section_title: str | None
    table_index: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Config Item Provenance ───────────────────────────────


class ConfigItemProvenanceRead(BaseModel):
    id: uuid.UUID
    data_source_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    agent_instance_id: uuid.UUID | None
    confidence: float
    extraction_context: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Search ───────────────────────────────────────────────


class DataSourceSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Natural language search query")
    data_source_ids: list[uuid.UUID] | None = Field(
        default=None, description="Limit search to specific data sources"
    )
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results to return")


class DataSourceSearchResult(BaseModel):
    chunk_id: uuid.UUID
    data_source_id: uuid.UUID
    data_source_name: str
    chunk_index: int
    content: str
    section_title: str | None
    table_index: int | None
    score: float = Field(description="Similarity score (0-1)")

    model_config = {"from_attributes": True}


# ── Extraction Preview ───────────────────────────────────


class ExtractionPreview(BaseModel):
    data_source_id: uuid.UUID
    data_source_name: str
    status: str
    chunk_count: int
    detected_entities: dict[str, int] = Field(
        default_factory=dict,
        description="Count of detected entity types, e.g. {'product': 2, 'characteristic': 15}",
    )
    sample_chunks: list[DataSourceChunkRead] = Field(
        default_factory=list, description="First few chunks as a preview"
    )
    extraction_error: str | None = None

    model_config = {"from_attributes": True}
