"""Pydantic schemas for agent API request/response validation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ── Agent Definition ───────────────────────────────────────────────────


class AgentDefinitionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = Field("", max_length=5000)
    system_prompt: str = Field("", max_length=100_000)
    model: str = Field("gpt-4o", max_length=100)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=1, le=1_000_000)
    allowed_tools: list[str] = []
    max_steps_per_run: int = Field(50, ge=1, le=1000)
    max_duration_seconds: int = Field(300, ge=10, le=3600)
    max_tokens_per_run: int = Field(100_000, ge=100, le=10_000_000)
    sandbox_enabled: bool = False
    memory_config: dict[str, Any] = {}
    governance_policy: dict[str, Any] = {}
    metadata: dict[str, Any] = {}


class AgentDefinitionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    system_prompt: str | None = Field(None, max_length=100_000)
    model: str | None = Field(None, max_length=100)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=1, le=1_000_000)
    allowed_tools: list[str] | None = None
    max_steps_per_run: int | None = Field(None, ge=1, le=1000)
    max_duration_seconds: int | None = Field(None, ge=10, le=3600)
    max_tokens_per_run: int | None = Field(None, ge=100, le=10_000_000)
    sandbox_enabled: bool | None = None
    memory_config: dict[str, Any] | None = None
    governance_policy: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    status: Literal["draft", "active", "disabled"] | None = None


class AgentDefinitionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    slug: str
    description: str
    status: str
    system_prompt: str
    model: str
    temperature: float | None
    max_tokens: int | None
    allowed_tools: list[str]
    max_steps_per_run: int
    max_duration_seconds: int
    max_tokens_per_run: int
    sandbox_enabled: bool
    memory_config: dict[str, Any]
    governance_policy: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Agent Instance ─────────────────────────────────────────────────────


class AgentInstanceCreate(BaseModel):
    input_data: dict[str, Any] = {}
    session_id: uuid.UUID | None = None


class AgentInstanceResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    definition_id: uuid.UUID
    status: str
    steps_executed: int
    tokens_used: int
    cost_usd: float
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Agent Session ──────────────────────────────────────────────────────


class AgentSessionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    instance_id: uuid.UUID
    status: str
    messages: list[dict[str, Any]]
    metadata: dict[str, Any]
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Agent Memory ───────────────────────────────────────────────────────


class MemoryWriteRequest(BaseModel):
    namespace: str = Field("default", min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    key: str = Field(..., min_length=1, max_length=500)
    value: dict[str, Any] = {}


class MemoryReadResponse(BaseModel):
    namespace: str
    key: str
    value: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Workflow ───────────────────────────────────────────────────────────


class WorkflowDefinitionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = ""
    definition: dict[str, Any] = Field(
        ...,
        description="DAG definition: {steps: [...], transitions: [...], entry_step: '...'}",
    )
    governance: dict[str, Any] = {}
    metadata: dict[str, Any] = {}


class WorkflowDefinitionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    slug: str
    description: str
    status: str
    definition: dict[str, Any]
    governance: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunCreate(BaseModel):
    input_data: dict[str, Any] = {}


class WorkflowRunResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    workflow_id: uuid.UUID
    status: str
    state: dict[str, Any]
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    error: str | None
    total_steps: int
    total_tokens: int
    total_cost_usd: float
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Tenant Tool ────────────────────────────────────────────────────────


class TenantToolCreate(BaseModel):
    tool_name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field("", max_length=5000)
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}
    endpoint_url: str | None = Field(None, max_length=2048)
    auth_config: dict[str, Any] = {}
    health_check_url: str | None = Field(None, max_length=2048)
    metadata: dict[str, Any] = {}

    @field_validator("endpoint_url", "health_check_url")
    @classmethod
    def validate_url_scheme(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.startswith(("https://",)):
            raise ValueError("Only HTTPS URLs are allowed")
        return v


class TenantToolResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    tool_name: str
    description: str
    source: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    endpoint_url: str | None
    is_active: bool
    health_check_url: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Agent Policy ───────────────────────────────────────────────────────


class AgentPolicyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=5000)
    max_spend_per_run_usd: float | None = Field(None, ge=0)
    max_spend_per_day_usd: float | None = Field(None, ge=0)
    max_spend_per_month_usd: float | None = Field(None, ge=0)
    allowed_tools: list[str] = []
    denied_tools: list[str] = []
    require_approval_for: list[str] = []
    approval_timeout_seconds: int = Field(300, ge=1, le=86400)
    approval_default_action: Literal["deny", "approve"] = "deny"
    max_requests_per_minute: int | None = Field(None, ge=1, le=10_000)
    max_steps_per_run: int | None = Field(None, ge=1, le=10_000)
    rules: dict[str, Any] = {}


class AgentPolicyResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str
    max_spend_per_run_usd: float | None
    max_spend_per_day_usd: float | None
    max_spend_per_month_usd: float | None
    allowed_tools: list[str]
    denied_tools: list[str]
    require_approval_for: list[str]
    approval_timeout_seconds: int
    approval_default_action: str
    max_requests_per_minute: int | None
    max_steps_per_run: int | None
    rules: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Pagination ─────────────────────────────────────────────────────────


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int
