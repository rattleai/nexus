"""Pydantic request/response schemas for the connector system."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Connector Definition (catalog) ──────────────────────


class ConnectorDefinitionRead(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    icon: str
    category: str
    connector_type: str
    auth_type: str
    is_system: bool
    is_active: bool
    version: str
    documentation_url: str | None
    tags: list[str] | None

    # Only include tool_definitions for detail view
    tool_definitions: list[dict[str, Any]] | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectorDefinitionList(BaseModel):
    items: list[ConnectorDefinitionRead]
    total: int


class RegisterMCPServerRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048, description="Streamable HTTP URL of the MCP server")
    name: str = Field(..., min_length=1, max_length=255, description="Display name for the connector")
    description: str = Field(default="", max_length=2048)


# ── OAuth Flow ──────────────────────────────────────────


class OAuthStartResponse(BaseModel):
    auth_url: str
    state: str


# ── Tenant Connection ───────────────────────────────────


class ConnectionCreateRequest(BaseModel):
    """Create a connection for API key / bearer token / no-auth connectors."""
    connector_slug: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=255)
    api_key: str | None = Field(default=None, description="API key (for api_key_api connectors)")
    bearer_token: str | None = Field(default=None, description="Bearer token (for bearer_token connectors)")


class ConnectionUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    config_overrides: dict[str, Any] | None = None


class ConnectionRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    connector_definition_id: uuid.UUID
    display_name: str
    account_identifier: str | None
    status: str
    status_message: str | None

    # Connector info (populated from join)
    connector_slug: str | None = None
    connector_name: str | None = None
    connector_icon: str | None = None
    connector_type: str | None = None

    # Stats
    tools_count: int = 0
    resources_count: int = 0

    # Timestamps
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectionDetailRead(ConnectionRead):
    """Extended connection view including cached tools and health."""
    health_status: dict[str, Any] | None = None
    health_checked_at: datetime | None = None
    cache_refreshed_at: datetime | None = None
    config_overrides: dict[str, Any] | None = None


class ConnectionList(BaseModel):
    items: list[ConnectionRead]
    total: int


# ── Connection Tools ────────────────────────────────────


class ConnectionToolRead(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] | None = None


# ── Health Check ────────────────────────────────────────


class ConnectionTestResult(BaseModel):
    status: str  # "ok" | "error"
    message: str
    latency_ms: int | None = None
