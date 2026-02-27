"""Tests for the SPA catch-all route and API path guarding."""

import pytest


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
    assert "max-age=" in response.headers["strict-transport-security"]
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["permissions-policy"]
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "x-request-id" in response.headers


@pytest.mark.asyncio
async def test_security_headers_on_spa_routes(client):
    """Security headers should also be present on SPA responses."""
    response = await client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in response.headers
