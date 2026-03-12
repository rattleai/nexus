"""Pydantic validation models for MCP tool inputs.

Ensures structured validation of MCP tool parameters before execution,
preventing malformed inputs from reaching internal services.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class MCPMessage(BaseModel):
    role: str = Field(..., pattern=r"^(system|user|assistant|tool)$")
    content: str = Field(..., min_length=1, max_length=200_000)


class AICompleteInput(BaseModel):
    model: str = Field(..., min_length=1, max_length=100)
    messages: list[MCPMessage] = Field(..., min_length=1, max_length=100)
    max_tokens: int | None = Field(None, ge=1, le=128_000)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    top_p: float | None = Field(None, ge=0.0, le=1.0)


class FileUploadInput(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_base64: str = Field(..., min_length=1)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError("Filename must not contain path traversal characters")
        return v


class JobCreateInput(BaseModel):
    job_type: str = Field(..., min_length=1, max_length=100)
    payload: dict | None = None


class WebhookCreateInput(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    events: list[str] = Field(..., min_length=1, max_length=50)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("URL must start with http:// or https://")
        return v
