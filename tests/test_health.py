from unittest.mock import AsyncMock, patch

import pytest

from cadprice import __version__


@pytest.mark.asyncio
async def test_health_returns_200(client):
    with (
        patch("cadprice.api_vendors.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api_vendors.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api_vendors.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
    ):
        response = await client.get("/api_vendors/v1/health")

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
        patch("cadprice.api_vendors.v1.health._check_db", new_callable=AsyncMock, return_value=False),
        patch("cadprice.api_vendors.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api_vendors.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
    ):
        response = await client.get("/api_vendors/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["services"]["db"] is False


@pytest.mark.asyncio
async def test_dashboard_returns_200(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert '<div id="root">' in response.text
