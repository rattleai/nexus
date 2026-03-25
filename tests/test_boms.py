"""Tests for BOM header and item endpoints."""

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
async def bom_client():
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
async def test_create_bom_requires_auth(bom_client):
    client, _ = bom_client
    response = await client.post("/api/v1/boms", json={
        "product_id": str(uuid.uuid4()),
        "name": "Manufacturing BOM",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_boms_requires_auth(bom_client):
    client, _ = bom_client
    response = await client.get(f"/api/v1/boms?product_id={uuid.uuid4()}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_bom_not_found(bom_client):
    client, app = bom_client
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
            response = await client.get(f"/api/v1/boms/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_add_bom_item_requires_auth(bom_client):
    client, _ = bom_client
    response = await client.post(f"/api/v1/boms/{uuid.uuid4()}/items", json={
        "part_number": "ENG-001",
        "part_name": "Engine Assembly",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_where_used_requires_auth(bom_client):
    client, _ = bom_client
    response = await client.get("/api/v1/boms/where-used/ENG-001")
    assert response.status_code == 401
