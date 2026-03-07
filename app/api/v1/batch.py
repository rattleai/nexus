"""Batch API endpoint for mobile clients.

Allows multiple API sub-requests in a single HTTP call, reducing
round trips, latency, and battery consumption on mobile devices.

Uses httpx AsyncClient to execute sub-requests internally against
the running ASGI app — no network overhead, full middleware support.

Usage:
    POST /api/v1/batch
    {
      "requests": [
        { "method": "GET", "path": "/api/v1/jobs?limit=5" },
        { "method": "GET", "path": "/api/v1/notifications?limit=10" }
      ]
    }
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/batch", tags=["batch"])

MAX_SUB_REQUESTS = 10
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
BLOCKED_PATHS = {"/api/v1/batch", "/api/v1/auth/refresh", "/api/v1/ws"}


class SubRequest(BaseModel):
    method: str = Field(..., description="HTTP method (GET, POST, PUT, PATCH, DELETE)")
    path: str = Field(..., description="API path (e.g. /api/v1/jobs?limit=5)")
    body: dict[str, Any] | None = Field(None, description="Request body for POST/PUT/PATCH")
    headers: dict[str, str] | None = Field(None, description="Additional headers")

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        v = v.upper()
        if v not in ALLOWED_METHODS:
            raise ValueError(f"Method must be one of {ALLOWED_METHODS}")
        return v

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not v.startswith("/api/"):
            raise ValueError("Path must start with /api/")
        normalized = v.split("?")[0]
        if normalized in BLOCKED_PATHS:
            raise ValueError(f"Path {normalized} is not allowed in batch requests")
        return v


class BatchRequest(BaseModel):
    requests: list[SubRequest] = Field(..., min_length=1, max_length=MAX_SUB_REQUESTS)


class SubResponse(BaseModel):
    status: int
    body: Any | None = None
    headers: dict[str, str] | None = None


class BatchResponse(BaseModel):
    responses: list[SubResponse]


@router.post("", response_model=BatchResponse)
async def batch_execute(
    batch: BatchRequest,
    request: Request,
) -> BatchResponse:
    """Execute multiple API sub-requests in a single call.

    All sub-requests share the parent request's authentication context.
    Sub-requests are executed sequentially against the ASGI app via httpx.
    Maximum 10 sub-requests per batch.
    """
    # Forward auth headers from the parent request
    forwarded_headers: dict[str, str] = {}
    for key in ("authorization", "x-api-key", "cookie", "x-request-id"):
        value = request.headers.get(key)
        if value:
            forwarded_headers[key] = value

    responses: list[SubResponse] = []

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=request.app),
        base_url="http://internal",
    ) as client:
        for sub in batch.requests:
            try:
                # Merge forwarded headers with sub-request specific headers
                req_headers = {**forwarded_headers}
                if sub.headers:
                    req_headers.update(sub.headers)

                # Build the request
                kwargs: dict[str, Any] = {
                    "method": sub.method,
                    "url": sub.path,
                    "headers": req_headers,
                }
                if sub.body is not None and sub.method in {"POST", "PUT", "PATCH"}:
                    kwargs["json"] = sub.body

                response = await client.request(**kwargs)

                # Parse response body
                body: Any = None
                if response.content:
                    try:
                        body = response.json()
                    except (json.JSONDecodeError, ValueError):
                        body = response.text

                responses.append(SubResponse(
                    status=response.status_code,
                    body=body,
                    headers=dict(response.headers) if response.status_code >= 400 else None,
                ))

            except Exception as exc:
                logger.warning("batch_sub_request_error", path=sub.path, error=str(exc))
                responses.append(SubResponse(status=500, body={"detail": "Internal error"}))

    return BatchResponse(responses=responses)
