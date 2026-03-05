from unittest.mock import AsyncMock, patch

import pytest

from app import __version__


@pytest.mark.asyncio
async def test_health_returns_200(client):
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
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
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=False),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
    ):
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["services"]["db"] is False
