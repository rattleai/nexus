"""Pydantic schemas for AI gateway request/response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ── Completion Request/Response ───────────────────────────


class AIMessage(BaseModel):
    role: Literal["system", "user", "assistant"] = Field(...)
    content: str = Field(..., min_length=1, max_length=200_000)


class AICompletionRequest(BaseModel):
    model: str = Field(..., description="Model ID from the catalog (e.g. 'gpt-4o', 'claude-sonnet-4-20250514')")
    messages: list[AIMessage] = Field(..., min_length=1, max_length=100)
    max_tokens: int | None = Field(default=None, ge=1, le=128_000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    stream: bool = Field(default=False)
    template_id: uuid.UUID | None = Field(
        default=None, description="Optional prompt template to prepend as system message"
    )
    fallback_models: list[str] | None = Field(default=None, max_length=3)

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list[AIMessage]) -> list[AIMessage]:
        total_len = sum(len(m.content) for m in v)
        if total_len > 1_000_000:
            raise ValueError("Total message content exceeds 1MB limit")
        return v


class AICompletionResponse(BaseModel):
    id: str
    model: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    billed_amount_usd: float
    latency_ms: int
    finish_reason: str | None = None


class AIStreamChunk(BaseModel):
    id: str
    delta: str
    finish_reason: str | None = None


class AIStreamUsage(BaseModel):
    """Final SSE message with usage stats after streaming completes."""

    type: str = "usage"
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    billed_amount_usd: float
    latency_ms: int


# ── Models ────────────────────────────────────────────────


class ModelInfoResponse(BaseModel):
    model_id: str
    provider: str
    display_name: str
    max_input_tokens: int
    max_output_tokens: int
    supports_streaming: bool
    supports_function_calling: bool
    supports_vision: bool
    available: bool


# ── Provider Keys (BYOK) ─────────────────────────────────


class ProviderKeyCreate(BaseModel):
    provider: str = Field(..., pattern=r"^[a-z_]+$", max_length=50)
    api_key: str = Field(..., min_length=10, max_length=500)
    display_name: str = Field(default="default", max_length=255)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        from app.db.models.ai import AIProvider

        valid = {p.value for p in AIProvider}
        if v not in valid:
            raise ValueError(f"Invalid provider '{v}'. Valid: {', '.join(sorted(valid))}")
        return v


class ProviderKeyResponse(BaseModel):
    id: uuid.UUID
    provider: str
    display_name: str
    is_active: bool
    last_used_at: datetime | None
    last_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Wallet ────────────────────────────────────────────────


class WalletBalanceResponse(BaseModel):
    balance_usd: Decimal
    lifetime_deposited_usd: Decimal
    lifetime_consumed_usd: Decimal
    currency: str = "USD"
    auto_refill_enabled: bool = False


class WalletTransactionResponse(BaseModel):
    id: uuid.UUID
    type: str
    amount_usd: Decimal
    balance_after_usd: Decimal
    description: str | None
    reference_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Prompt Templates ──────────────────────────────────────


class PromptTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    system_prompt: str = Field(..., min_length=1, max_length=50_000)
    description: str | None = Field(default=None, max_length=1000)
    variables: list[str] | None = Field(default=None, max_length=20)


class PromptTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=50_000)
    description: str | None = Field(default=None, max_length=1000)
    variables: list[str] | None = None
    is_default: bool | None = None


class PromptTemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    system_prompt: str
    variables: list[str] | None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Usage Stats ───────────────────────────────────────────


class ModelUsageSummary(BaseModel):
    model: str
    provider: str
    request_count: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    total_billed_usd: float


class AIUsageResponse(BaseModel):
    total_requests: int
    total_tokens: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_billed_usd: float
    by_model: list[ModelUsageSummary]
    period_start: datetime
    period_end: datetime
