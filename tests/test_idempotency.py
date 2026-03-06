"""Tests for the idempotency guard."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from app.core.idempotency import IdempotencyGuard


def _make_request(headers: dict | None = None, method: str = "POST", path: str = "/api/v1/test") -> MagicMock:
    """Create a mock Request object."""
    req = MagicMock(spec=Request)
    req.headers = headers or {}
    req.method = method
    req.url = MagicMock()
    req.url.path = path
    req.state = MagicMock()
    req.state.tenant = None
    # Clear attributes that should not exist unless set
    del req.state.idempotency_response
    del req.state.idempotency_key
    del req.state.idempotency_ttl
    return req


@pytest.mark.asyncio
async def test_idempotency_no_header_optional():
    """Without header and required=False, should pass through."""
    guard = IdempotencyGuard(required=False)
    request = _make_request()
    await guard(request)
    assert not hasattr(request.state, "idempotency_key") or request.state.idempotency_key is None


@pytest.mark.asyncio
async def test_idempotency_no_header_required():
    """Without header and required=True, should raise 400."""
    from fastapi import HTTPException

    guard = IdempotencyGuard(required=True)
    request = _make_request()
    with pytest.raises(HTTPException) as exc_info:
        await guard(request)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_idempotency_key_too_long():
    """Key longer than 255 chars should be rejected."""
    from fastapi import HTTPException

    guard = IdempotencyGuard()
    request = _make_request(headers={"X-Idempotency-Key": "a" * 256})
    with pytest.raises(HTTPException) as exc_info:
        await guard(request)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_idempotency_cache_miss():
    """On cache miss, should store key info on request state."""
    guard = IdempotencyGuard(ttl=3600)
    request = _make_request(headers={"X-Idempotency-Key": "test-key-123"})

    with patch("app.core.idempotency.redis_pool") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        await guard(request)

    assert request.state.idempotency_key == "idempotency:global:POST:/api/v1/test:test-key-123"
    assert request.state.idempotency_ttl == 3600


@pytest.mark.asyncio
async def test_idempotency_cache_hit():
    """On cache hit, should set idempotency_response on request state."""
    guard = IdempotencyGuard()
    request = _make_request(headers={"X-Idempotency-Key": "test-key-123"})

    cached_data = json.dumps({"status_code": 201, "body": {"id": "abc"}})
    with patch("app.core.idempotency.redis_pool") as mock_redis:
        mock_redis.get = AsyncMock(return_value=cached_data)
        await guard(request)

    assert hasattr(request.state, "idempotency_response")
    assert request.state.idempotency_response.status_code == 201
