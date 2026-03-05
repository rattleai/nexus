"""Tests for tenant management endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.config import settings
from app.main import create_app

ADMIN_HEADERS = {"X-Admin-Key": settings.ADMIN_KEY or settings.SECRET_KEY}


def _make_tenant(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "name": "Test Tenant",
        "slug": "test-tenant",
        "plan": "free",
        "is_active": True,
        "settings": {},
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


@pytest.fixture
async def tenant_client():
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_celery", new_callable=AsyncMock, return_value=True),
        patch("app.core.redis.redis_pool", new_callable=AsyncMock),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=ADMIN_HEADERS) as ac:
            yield ac, app


@pytest.mark.asyncio
async def test_tenant_requires_admin_key():
    """Tenant endpoints should reject requests without admin key."""
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_celery", new_callable=AsyncMock, return_value=True),
        patch("app.core.redis.redis_pool", new_callable=AsyncMock),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/tenants")
            assert response.status_code == 422  # Missing header

            response = await client.get(
                "/api/v1/tenants",
                headers={"X-Admin-Key": "wrong-key"},
            )
            assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_tenant_invalid_slug(tenant_client):
    """Slugs with invalid characters should be rejected."""
    client, _ = tenant_client
    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Test", "slug": "INVALID SLUG!"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_tenant_slug_too_short(tenant_client):
    """Single-char slug should be rejected by regex pattern."""
    client, _ = tenant_client
    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Test", "slug": "a"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_tenants(tenant_client):
    """Tenant listing returns cursor-paginated response."""
    client, app = tenant_client

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        response = await client.get("/api/v1/tenants")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "has_more" in data
        assert data["items"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_tenant_not_found(tenant_client):
    """Getting a non-existent tenant should return 404."""
    client, app = tenant_client

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        response = await client.get(f"/api/v1/tenants/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_tenant_duplicate_slug(tenant_client):
    """Duplicate slug should return 409."""
    client, app = tenant_client
    existing = _make_tenant()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = mock_result

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        response = await client.post(
            "/api/v1/tenants",
            json={"name": "Test", "slug": "test-tenant"},
        )
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()
