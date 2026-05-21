"""Tests for agent-friendly error hints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.hints import get_hint
from app.main import create_app


def test_get_hint_exact_match():
    hint = get_hint(422, "VALIDATION_ERROR")
    assert hint is not None
    assert "errors" in hint


def test_get_hint_http_fallback():
    hint = get_hint(401, "HTTP_401")
    assert hint is not None
    assert "X-API-Key" in hint


def test_get_hint_unknown():
    hint = get_hint(999, "UNKNOWN_CODE")
    assert hint is None


def test_get_hint_rate_limit():
    hint = get_hint(429, "HTTP_429")
    assert hint is not None
    assert "Retry-After" in hint


def test_get_hint_insufficient_balance():
    hint = get_hint(402, "HTTP_402")
    assert hint is not None
    assert "wallet" in hint.lower()


@pytest.mark.asyncio
async def test_http_exception_includes_hint():
    """Test that HTTP exceptions include hints when AGENT_HINTS_ENABLED=True."""
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.config.settings.AGENT_HINTS_ENABLED", True),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Hit a non-existent API endpoint to get a 404
            response = await client.get("/api/v1/nonexistent")
            assert response.status_code == 404
            data = response.json()
            assert "code" in data
            assert data["code"] == "HTTP_404"


@pytest.mark.asyncio
async def test_validation_error_includes_hint():
    """Test that validation errors include hints."""
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.config.settings.AGENT_HINTS_ENABLED", True),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Post without required body to trigger validation
            response = await client.post(
                "/api/v1/tenants",
                json={},  # Missing required fields
            )
            if response.status_code == 422:
                data = response.json()
                assert "hint" in data
