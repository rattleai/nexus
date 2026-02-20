from unittest.mock import AsyncMock, patch

import pytest

from cadprice import __version__


@pytest.mark.asyncio
async def test_health_returns_200(client):
    with (
        patch("cadprice.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
    ):
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == __version__
    assert data["services"]["db"] is True
    assert data["services"]["redis"] is True
    assert data["services"]["storage"] is True


@pytest.mark.asyncio
async def test_health_degraded_when_db_down(client):
    with (
        patch("cadprice.api.v1.health._check_db", new_callable=AsyncMock, return_value=False),
        patch("cadprice.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
    ):
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["services"]["db"] is False


@pytest.mark.asyncio
async def test_health_fragment_returns_html(client):
    with (
        patch("cadprice.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
    ):
        response = await client.get("/api/v1/health/fragment")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Connected" in response.text
    assert "Database" in response.text
    assert "Redis" in response.text
    assert "Storage" in response.text


@pytest.mark.asyncio
async def test_health_fragment_shows_unavailable(client):
    with (
        patch("cadprice.api.v1.health._check_db", new_callable=AsyncMock, return_value=False),
        patch("cadprice.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api.v1.health._check_storage", new_callable=AsyncMock, return_value=False),
    ):
        response = await client.get("/api/v1/health/fragment")

    assert response.status_code == 200
    assert "Unavailable" in response.text


@pytest.mark.asyncio
async def test_dashboard_returns_200(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "CADPrice" in response.text


@pytest.mark.asyncio
async def test_dashboard_contains_version(client):
    response = await client.get("/")
    assert __version__ in response.text
