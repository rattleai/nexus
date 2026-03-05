"""Tests for API key management endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_tenant, get_db
from app.main import create_app


def _make_tenant():
    return MagicMock(
        id=uuid.uuid4(),
        name="Test",
        slug="test",
        plan="free",
        is_active=True,
        settings={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deleted_at=None,
    )


@pytest.fixture
async def auth_client():
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_celery", new_callable=AsyncMock, return_value=True),
        patch("app.core.redis.redis_pool", new_callable=AsyncMock),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, app


@pytest.mark.asyncio
async def test_create_api_key_requires_auth(auth_client):
    """Creating an API key requires X-API-Key header."""
    client, _ = auth_client
    response = await client.post("/api/v1/api-keys", json={"name": "my-key"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_api_keys_requires_auth(auth_client):
    client, _ = auth_client
    response = await client.get("/api/v1/api-keys")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_revoke_nonexistent_key(auth_client):
    """Revoking a non-existent key should return 404."""
    client, app = auth_client
    tenant = _make_tenant()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        response = await client.delete(f"/api/v1/api-keys/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_api_keys_returns_paginated(auth_client):
    """Listing API keys returns cursor-paginated response."""
    client, app = auth_client
    tenant = _make_tenant()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        response = await client.get("/api/v1/api-keys")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "has_more" in data
        assert data["items"] == []
    finally:
        app.dependency_overrides.clear()
