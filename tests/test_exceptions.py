"""Tests for global exception handlers."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Query
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def exc_client():
    """Client with test routes added to a fresh app to avoid router pollution."""
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_celery", new_callable=AsyncMock, return_value=True),
        patch("app.core.redis.redis_pool", new_callable=AsyncMock),
    ):
        from app.main import create_app

        app = create_app()

        # Add test routes directly to the app (not to the shared v1_router)
        @app.get("/api/v1/_test_validation")
        async def _test_validation(num: int = Query(...)):
            return {"num": num}

        @app.get("/api/v1/_test_crash")
        async def _test_crash():
            raise RuntimeError("Something broke")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_http_exception_returns_consistent_format(client):
    """HTTP exceptions should return {detail, code} format."""
    response = await client.get("/api/v1/nonexistent-endpoint-xyz")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "code" in data


@pytest.mark.asyncio
async def test_validation_error_returns_field_errors(exc_client):
    """Validation errors should return structured field-level errors."""
    response = await exc_client.get("/api/v1/_test_validation")
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "VALIDATION_ERROR"
    assert "errors" in data
    assert len(data["errors"]) > 0
    assert "field" in data["errors"][0]
    assert "message" in data["errors"][0]


@pytest.mark.asyncio
async def test_unhandled_exception_returns_500(exc_client):
    """Unhandled exceptions should return 500 with generic message."""
    response = await exc_client.get("/api/v1/_test_crash")
    assert response.status_code == 500
    data = response.json()
    assert data["detail"] == "Internal server error"
    assert data["code"] == "INTERNAL_ERROR"
    # Stack trace should NOT be in response
    assert "RuntimeError" not in response.text
    assert "Something broke" not in response.text
