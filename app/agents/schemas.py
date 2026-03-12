"""Pydantic schemas for agent API request/response validation."""

from __future__ import annotations

import json as _json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── Shared Validators ─────────────────────────────────────────────────


def _validate_json_size(v: dict[str, Any], max_bytes: int = 65_536) -> dict[str, Any]:
    """Reject payloads larger than max_bytes when serialized."""
    if len(_json.dumps(v, default=str)) > max_bytes:
        raise ValueError(f"JSON payload exceeds maximum size of {max_bytes} bytes")
    return v


_SENSITIVE_KEYS = {"token", "key", "secret", "password", "client_secret", "api_key"}


def _validate_tool_names(v: list[str]) -> list[str]:
    if len(v) > 100:
        raise ValueError("Maximum 100 tools allowed")
    for name in v:
        if not name or len(name) > 100:
            raise ValueError("Invalid tool name: must be 1-100 characters")
    return v


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

    @field_validator("allowed_tools")
    @classmethod
    def validate_tool_names(cls, v: list[str]) -> list[str]:
        return _validate_tool_names(v)

    @field_validator("memory_config", "governance_policy", "metadata")
    @classmethod
    def validate_json_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_size(v)


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
    expected_version: int | None = None

    @field_validator("allowed_tools")
    @classmethod
    def validate_tool_names(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return _validate_tool_names(v)


class AgentDefinitionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    slug: str
    description: str
    status: str
    version: int
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
    idempotency_key: str | None = Field(None, max_length=255)


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

    @field_validator("definition")
    @classmethod
    def validate_workflow_structure(cls, v: dict[str, Any]) -> dict[str, Any]:
        required_keys = {"steps", "transitions", "entry_step"}
        missing = required_keys - set(v.keys())
        if missing:
            raise ValueError(f"Workflow definition missing required keys: {missing}")
        if not isinstance(v["steps"], list) or not v["steps"]:
            raise ValueError("Workflow definition must have at least one step")
        if not isinstance(v["transitions"], list):
            raise ValueError("Workflow transitions must be a list")
        step_names = set()
        for step in v["steps"]:
            if not isinstance(step, dict) or "name" not in step or "agent_id" not in step:
                raise ValueError("Each workflow step must have 'name' and 'agent_id'")
            step_names.add(step["name"])
        if not isinstance(v["entry_step"], str) or not v["entry_step"]:
            raise ValueError("entry_step must be a non-empty string")
        if v["entry_step"] not in step_names:
            raise ValueError(f"entry_step '{v['entry_step']}' does not match any step name")
        return v

    @field_validator("governance", "metadata")
    @classmethod
    def validate_json_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_size(v)


class WorkflowDefinitionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    slug: str
    description: str
    status: str
    version: int
    definition: dict[str, Any]
    governance: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunCreate(BaseModel):
    input_data: dict[str, Any] = {}

    @field_validator("input_data")
    @classmethod
    def validate_input_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(_json.dumps(v, default=str)) > 1_048_576:  # 1MB
            raise ValueError("input_data exceeds maximum size of 1MB")
        return v


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
        from urllib.parse import urlparse
        parsed = urlparse(v)
        if parsed.scheme != "https":
            raise ValueError("Only HTTPS URLs are allowed")
        if not parsed.hostname:
            raise ValueError("URL must have a valid hostname")
        # Block private/reserved IP ranges (SSRF protection)
        import ipaddress
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                raise ValueError("URLs pointing to private/internal networks are not allowed")
        except ValueError as exc:
            if "not allowed" in str(exc):
                raise
            # hostname is a domain name, not IP — that's fine
        return v

    @field_validator("input_schema", "output_schema", "auth_config", "metadata")
    @classmethod
    def validate_json_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_size(v)


class TenantToolResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    tool_name: str
    description: str
    source: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    endpoint_url: str | None
    auth_config: dict[str, Any] = {}
    is_active: bool
    health_check_url: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("auth_config", mode="before")
    @classmethod
    def mask_auth_secrets(cls, v: dict[str, Any] | None) -> dict[str, Any]:
        """Mask sensitive fields in auth_config for API responses."""
        if not v:
            return {}
        masked = dict(v)
        for field_name in _SENSITIVE_KEYS:
            if masked.get(field_name):
                masked[field_name] = "***"
        return masked


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

    @field_validator("allowed_tools", "denied_tools", "require_approval_for")
    @classmethod
    def validate_tool_names(cls, v: list[str]) -> list[str]:
        return _validate_tool_names(v)

    @field_validator("rules")
    @classmethod
    def validate_rules_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_size(v)


class AgentPolicyResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str
    version: int
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
