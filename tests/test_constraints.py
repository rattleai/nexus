"""Tests for constraint rule, group, and variant table endpoints."""

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


def _make_api_key(tenant):
    api_key = MagicMock()
    api_key.scopes = ["products:read", "products:write"]
    api_key.tenant = tenant
    return api_key


@pytest.fixture
async def constraint_client():
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
async def test_create_constraint_rule_requires_auth(constraint_client):
    client, _ = constraint_client
    response = await client.post("/api/v1/constraints/rules", json={
        "product_id": str(uuid.uuid4()),
        "name": "Engine requires transmission",
        "constraint_type": "requires",
        "expression": {"type": "requires", "if": {"char": "engine", "op": "eq", "value": "V8"}, "then": {"char": "transmission", "op": "in", "value": ["auto"]}},
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_validate_expression_requires(constraint_client):
    """Validate endpoint should work with mock auth."""
    client, app = constraint_client
    tenant = _make_tenant()

    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        mock_key = _make_api_key(tenant)
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=mock_key):
            response = await client.post("/api/v1/constraints/rules/validate", json={
                "constraint_type": "requires",
                "expression": {
                    "type": "requires",
                    "if": {"char": "engine", "op": "eq", "value": "V8"},
                    "then": {"char": "transmission", "op": "in", "value": ["auto_6"]},
                },
            })
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
        assert data["errors"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_validate_expression_missing_if(constraint_client):
    client, app = constraint_client
    tenant = _make_tenant()

    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        mock_key = _make_api_key(tenant)
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=mock_key):
            response = await client.post("/api/v1/constraints/rules/validate", json={
                "constraint_type": "requires",
                "expression": {"type": "requires", "then": {"char": "x", "op": "eq", "value": "y"}},
            })
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert len(data["errors"]) > 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_validate_expression_excludes(constraint_client):
    client, app = constraint_client
    tenant = _make_tenant()

    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        mock_key = _make_api_key(tenant)
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=mock_key):
            response = await client.post("/api/v1/constraints/rules/validate", json={
                "constraint_type": "excludes",
                "expression": {
                    "type": "excludes",
                    "if": {"char": "trim", "op": "eq", "value": "base"},
                    "then": {"char": "sunroof", "op": "eq", "value": "panoramic"},
                },
            })
        assert response.status_code == 200
        assert response.json()["is_valid"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_constraint_rule_not_found(constraint_client):
    client, app = constraint_client
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
            response = await client.get(f"/api/v1/constraints/rules/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
