"""Tests for the SPA catch-all route and API path guarding."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def spa_dist(tmp_path):
    """Create a temporary SPA dist directory with index.html."""
    index_html = tmp_path / "index.html"
    index_html.write_text('<!DOCTYPE html><html><body><div id="root"></div></body></html>')
    with patch("app.main.SPA_DIR", tmp_path):
        yield


@pytest.mark.asyncio
async def test_spa_root_serves_index_html(client):
    """Root path should serve the SPA index.html."""
    response = await client.get("/")
    assert response.status_code == 200
    assert '<div id="root">' in response.text


@pytest.mark.asyncio
async def test_spa_arbitrary_path_serves_index_html(client):
    """Any non-API path should serve index.html for client-side routing."""
    response = await client.get("/dashboard/settings")
    assert response.status_code == 200
    assert '<div id="root">' in response.text


@pytest.mark.asyncio
async def test_unregistered_api_route_returns_json_404(client):
    """Unregistered API routes should return JSON 404, not the SPA."""
    response = await client.get("/api/v1/nonexistent")
    assert response.status_code == 404
    data = response.json()
    assert data["detail"] == "Not found"
    assert data["code"] == "HTTP_404"


@pytest.mark.asyncio
async def test_unknown_api_version_returns_json_404(client):
    """Unknown API versions should return JSON 404."""
    response = await client.get("/api/v2/anything")
    assert response.status_code == 404
    data = response.json()
    assert data["detail"] == "Not found"


@pytest.mark.asyncio
async def test_bare_api_path_returns_json_404(client):
    """Bare /api path should return JSON 404."""
    response = await client.get("/api")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_security_headers_present(client):
    """Security headers should be present on all responses."""
    response = await client.get("/api/v1/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["permissions-policy"]
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "x-request-id" in response.headers


@pytest.mark.asyncio
async def test_security_headers_include_hsts_in_production():
    """HSTS header should be present when DEBUG is off."""
    with (
        patch("app.api.middleware.settings") as mock_settings,
        patch("app.core.redis.redis_pool"),
    ):
        mock_settings.DEBUG = False
        mock_settings.CORS_ORIGINS = "http://localhost:3000"
        mock_settings.API_V1_PREFIX = "/api/v1"
        mock_settings.SECRET_KEY = "test"
        mock_settings.RATE_LIMIT_DEFAULT = 100
        mock_settings.RATE_LIMIT_WINDOW_SECONDS = 60
        mock_settings.RATE_LIMIT_AUTH_ENDPOINTS = 10
        from app.main import create_app

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
        assert "max-age=" in response.headers["strict-transport-security"]


@pytest.mark.asyncio
async def test_security_headers_on_spa_routes(client):
    """Security headers should also be present on SPA responses."""
    response = await client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in response.headers
