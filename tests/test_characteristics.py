"""Tests for characteristic, group, value, and assignment endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_tenant, get_db
from app.main import create_app


def _make_tenant():
    return MagicMock(
        id=uuid.uuid4(), name="Test", slug="test", plan="free", is_active=True,
    )


@pytest.fixture
async def char_client():
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
async def test_create_characteristic_requires_auth(char_client):
    client, _ = char_client
    response = await client.post("/api/v1/characteristics", json={
        "name": "Color", "slug": "color", "char_type": "enum",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_characteristics_requires_auth(char_client):
    client, _ = char_client
    response = await client.get("/api/v1/characteristics")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_group_requires_auth(char_client):
    client, _ = char_client
    response = await client.post("/api/v1/characteristics/groups", json={
        "name": "Exterior", "slug": "exterior",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_characteristic_not_found(char_client):
    client, app = char_client
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
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=None):
            response = await client.get(f"/api/v1/characteristics/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_assign_characteristic_requires_auth(char_client):
    client, _ = char_client
    response = await client.post("/api/v1/characteristics/assign", json={
        "product_id": str(uuid.uuid4()),
        "characteristic_id": str(uuid.uuid4()),
    })
    assert response.status_code == 401
