"""Tests for MCP billing tools."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.tools.billing import (
    billing_get_subscription,
    billing_get_wallet_balance,
    billing_list_plans,
)


def _make_tenant():
    return MagicMock(id=uuid.uuid4(), name="Test", is_active=True)


@pytest.mark.asyncio
async def test_billing_get_wallet_balance():
    """Test getting wallet balance."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_wallet = MagicMock(
        balance_tokens=5000,
        lifetime_purchased=10000,
        lifetime_consumed=5000,
    )

    with patch("app.mcp.tools.billing.wallet_service") as ws:
        ws._get_or_create_wallet = AsyncMock(return_value=mock_wallet)
        ws.get_balance = AsyncMock(return_value=5000)

        result = await billing_get_wallet_balance(tenant=tenant, db=mock_db)

    assert result["balance_tokens"] == 5000
    assert result["lifetime_purchased"] == 10000
    assert result["lifetime_consumed"] == 5000


@pytest.mark.asyncio
async def test_billing_get_wallet_balance_initializes_when_zero():
    """Test that balance is initialized when Redis returns 0 but DB has tokens."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_wallet = MagicMock(
        balance_tokens=5000,
        lifetime_purchased=10000,
        lifetime_consumed=5000,
    )

    with patch("app.mcp.tools.billing.wallet_service") as ws:
        ws._get_or_create_wallet = AsyncMock(return_value=mock_wallet)
        ws.get_balance = AsyncMock(side_effect=[0, 5000])
        ws.initialize_balance = AsyncMock()

        result = await billing_get_wallet_balance(tenant=tenant, db=mock_db)

    ws.initialize_balance.assert_awaited_once()
    assert result["balance_tokens"] == 5000


@pytest.mark.asyncio
async def test_billing_list_plans():
    """Test listing available plans."""
    mock_db = AsyncMock()

    mock_plan = MagicMock()
    mock_plan.id = uuid.uuid4()
    mock_plan.name = "Pro"
    mock_plan.tier = MagicMock(value="pro")
    mock_plan.price_cents = 4999
    mock_plan.billing_period = "monthly"
    mock_plan.limits = {"max_tokens": 1_000_000}
    mock_plan.features = ["priority_support"]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_plan]
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await billing_list_plans(db=mock_db)

    assert len(result) == 1
    assert result[0]["name"] == "Pro"
    assert result[0]["price_cents"] == 4999


@pytest.mark.asyncio
async def test_billing_get_subscription_none():
    """Test getting subscription when none exists."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await billing_get_subscription(tenant=tenant, db=mock_db)

    assert result["status"] == "none"
    assert result["plan"] is None


@pytest.mark.asyncio
async def test_billing_get_subscription_active():
    """Test getting an active subscription."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_plan = MagicMock()
    mock_plan.id = uuid.uuid4()
    mock_plan.name = "Pro"
    mock_plan.tier = MagicMock(value="pro")

    mock_sub = MagicMock()
    mock_sub.id = uuid.uuid4()
    mock_sub.status = MagicMock(value="active")
    mock_sub.plan = mock_plan
    mock_sub.current_period_start = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")
    mock_sub.current_period_end = MagicMock(isoformat=lambda: "2026-02-01T00:00:00")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_sub
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await billing_get_subscription(tenant=tenant, db=mock_db)

    assert result["status"] == "active"
    assert result["plan"]["name"] == "Pro"
