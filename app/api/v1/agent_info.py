"""Agent capabilities discovery endpoint.

Returns a machine-readable summary of API capabilities, authentication methods,
rate limits, and available features so AI agents can self-configure without
parsing OpenAPI schemas or documentation.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/agent", tags=["agent"])


class RateLimits(BaseModel):
    standard_requests_per_window: int
    window_seconds: int
    ai_requests_per_window: int


class AuthMethods(BaseModel):
    api_key: bool = True
    bearer_jwt: bool
    oauth_client_credentials: bool


class BatchConfig(BaseModel):
    enabled: bool = True
    max_sub_requests: int = 10
    endpoint: str = "/api/v1/batch"


class AgentOptimizations(BaseModel):
    """Optimizations available for agent requests."""
    lean_headers: bool = True
    lean_headers_description: str = (
        "Agent requests skip browser-only headers (CSP, X-Frame-Options, HSTS, "
        "Permissions-Policy, Referrer-Policy) reducing ~400 bytes per response."
    )
    etag_caching: bool = True
    etag_description: str = "Send If-None-Match with ETag value to get 304 Not Modified."
    gzip_compression: bool = True
    gzip_description: str = "Responses >1KB are gzip-compressed. Send Accept-Encoding: gzip."
    idempotency_keys: bool = True
    idempotency_description: str = (
        "Send X-Idempotency-Key header on POST/PUT/PATCH for safe retries. "
        "Cached for 24 hours."
    )
    prefer_minimal: bool = True
    prefer_minimal_description: str = (
        "Send 'Prefer: return=minimal' header on POST/PUT/PATCH to receive "
        "only {id, status} instead of the full resource."
    )
    error_hints: bool
    error_hints_description: str = (
        "Error responses include an agent-friendly 'hint' field with actionable guidance."
    )


class AgentCapabilities(BaseModel):
    api_version: str = "v1"
    base_url: str = "/api/v1"
    openapi_url: str = "/api/v1/openapi.json"
    auth: AuthMethods
    rate_limits: RateLimits
    batch: BatchConfig
    optimizations: AgentOptimizations
    recognized_agent_headers: list[str]
    features: dict[str, bool]


@router.get(
    "/capabilities",
    response_model=AgentCapabilities,
    summary="Agent capabilities discovery",
    description=(
        "Returns a machine-readable summary of API capabilities, auth methods, "
        "rate limits, and available optimizations for AI agent integration. "
        "No authentication required."
    ),
)
async def get_agent_capabilities() -> AgentCapabilities:
    return AgentCapabilities(
        auth=AuthMethods(
            bearer_jwt=settings.AUTH_ENABLED,
            oauth_client_credentials=settings.OAUTH_CLIENT_CREDENTIALS_ENABLED,
        ),
        rate_limits=RateLimits(
            standard_requests_per_window=settings.RATE_LIMIT_DEFAULT,
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
            ai_requests_per_window=settings.RATE_LIMIT_AI_REQUESTS,
        ),
        batch=BatchConfig(),
        optimizations=AgentOptimizations(
            error_hints=settings.AGENT_HINTS_ENABLED,
        ),
        recognized_agent_headers=["X-Agent-Name", "X-API-Key"],
        features={
            "ai_gateway": settings.AI_ENABLED,
            "mcp_server": settings.MCP_ENABLED,
            "agent_execution": settings.AGENT_EXECUTION_ENABLED,
            "webhooks": True,
            "batch_api": True,
        },
    )
