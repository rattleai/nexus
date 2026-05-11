"""Tests for product family and product CRUD endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_tenant, get_db
from app.apps.cpq.models.product import ProductStatus
from app.main import create_app


def _make_tenant():
    return MagicMock(
        id=uuid.uuid4(),
        name="Test",
        slug="test",
        plan="free",
        is_active=True,
    )


def _make_api_key(tenant):
    api_key = MagicMock()
    api_key.scopes = ["products:read", "products:write"]
    api_key.tenant = tenant
    return api_key


def _make_product(tenant_id, **overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "family_id": None,
        "name": "Widget Pro",
        "slug": "widget-pro",
        "description": "A configurable widget",
        "sku_prefix": "WP",
        "status": ProductStatus.DRAFT,
        "metadata_": {},
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "version": 1,
        "created_by": None,
        "updated_by": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_family(tenant_id, **overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "name": "Widgets",
        "slug": "widgets",
        "description": "Widget family",
        "metadata_": {},
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "version": 1,
        "created_by": None,
        "updated_by": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


@pytest.fixture
async def product_client():
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
async def test_create_product_requires_auth(product_client):
    client, _ = product_client
    response = await client.post(
        "/api/v1/products",
        json={
            "name": "Test",
            "slug": "test",
            "status": "draft",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_products_requires_auth(product_client):
    client, _ = product_client
    response = await client.get("/api/v1/products")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_family_requires_auth(product_client):
    client, _ = product_client
    response = await client.post(
        "/api/v1/products/families",
        json={
            "name": "Test Family",
            "slug": "test-family",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_product_not_found(product_client):
    client, app = product_client
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
        mock_key = _make_api_key(tenant)
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=mock_key):
            response = await client.get(f"/api/v1/products/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_family_not_found(product_client):
    client, app = product_client
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
        mock_key = _make_api_key(tenant)
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=mock_key):
            response = await client.get(f"/api/v1/products/families/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
