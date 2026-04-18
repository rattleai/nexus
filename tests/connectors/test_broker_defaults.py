"""Broker default + router status invariants.

Locks in the "Composio by default, silent fallback to in-house" posture so
a later refactor can't accidentally revert the default or break the
fallback contract.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import settings
from app.connectors.brokers.router import BrokerRouter, broker_router
from app.connectors.models import BrokerType


def test_default_broker_is_composio():
    """The platform ships with Composio as the recommended default."""
    assert settings.CONNECTOR_DEFAULT_BROKER == BrokerType.COMPOSIO.value


def test_all_builtin_yamls_use_composio():
    """Every built-in YAML should declare broker: composio so tenants get
    the managed catalog on day one."""
    from app.connectors.registry import connector_registry

    defs = connector_registry.load_builtins()
    assert defs, "built-in catalog must not be empty"
    for d in defs:
        assert d.get("broker") == "composio", (
            f"{d.get('slug')} does not default to Composio"
        )


def test_register_mcp_server_stays_in_house(slack_oauth_connector):
    """Custom MCP servers always go through the in-house broker.

    Composio only covers its own catalog — arbitrary tenant-registered
    MCP URLs must use our own path.
    """
    from app.connectors.registry import connector_registry

    async def _run():
        # Use a MagicMock db just enough to exercise the code path
        from unittest.mock import MagicMock, AsyncMock

        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        connector = await connector_registry.register_mcp_server(
            db,
            url="https://example.com/mcp",
            name="My Custom",
            description="",
        )
        return connector

    import asyncio
    connector = asyncio.get_event_loop().run_until_complete(_run())
    assert connector.broker == BrokerType.IN_HOUSE


def test_status_reports_composio_unavailable_without_api_key():
    """When COMPOSIO_API_KEY is empty, status() must report the effective
    default as in_house so ops can see the fallback."""
    original = settings.COMPOSIO_API_KEY
    settings.COMPOSIO_API_KEY = ""
    try:
        # Force a fresh composio client attempt
        from app.connectors.brokers.composio import composio_broker
        composio_broker._attempted = False
        composio_broker._available = False
        composio_broker._client = None

        status = broker_router.status()
        assert status.default_broker == BrokerType.COMPOSIO.value
        assert status.composio_configured is False
        assert status.composio_available is False
        assert status.effective_default == BrokerType.IN_HOUSE.value
    finally:
        settings.COMPOSIO_API_KEY = original


def test_for_connector_falls_back_to_in_house_when_composio_unavailable(
    slack_oauth_connector,
):
    from app.connectors.brokers.in_house import in_house_broker

    original = settings.COMPOSIO_API_KEY
    settings.COMPOSIO_API_KEY = ""
    try:
        from app.connectors.brokers.composio import composio_broker
        composio_broker._attempted = False
        composio_broker._available = False
        composio_broker._client = None

        router = BrokerRouter()
        picked = router.for_connector(slack_oauth_connector)
        assert picked is in_house_broker
    finally:
        settings.COMPOSIO_API_KEY = original
