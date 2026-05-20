"""Broker default + router status invariants.

Locks in the "in-house by default, opt-in Composio" posture so a later
refactor can't silently route tenant OAuth tokens through an external
broker. Individual YAMLs may still pin broker=composio, but the unset
default stays in-house.
"""

from __future__ import annotations

from app.config import settings
from app.connectors.brokers.router import BrokerRouter, broker_router
from app.connectors.models import BrokerType


def test_default_broker_is_in_house():
    """The platform ships with in-house as the default broker.

    Composio is opt-in via per-connector YAML (broker: composio) and via
    CONNECTOR_DEFAULT_BROKER once COMPOSIO_API_KEY is provisioned.
    """
    assert BrokerType.IN_HOUSE.value == settings.CONNECTOR_DEFAULT_BROKER


def test_all_builtin_yamls_pin_broker_explicitly():
    """Every built-in YAML should declare its broker explicitly so the
    default only affects future / plugin connectors."""
    from app.connectors.registry import connector_registry

    defs = connector_registry.load_builtins()
    assert defs, "built-in catalog must not be empty"
    for d in defs:
        broker = d.get("broker")
        assert broker in {"composio", "in_house"}, f"{d.get('slug')} has unexpected broker: {broker!r}"


def test_register_mcp_server_stays_in_house(slack_oauth_connector):
    """Custom MCP servers always go through the in-house broker.

    Composio only covers its own catalog — arbitrary tenant-registered
    MCP URLs must use our own path.
    """
    from app.connectors.registry import connector_registry

    async def _run():
        # Use a MagicMock db just enough to exercise the code path
        from unittest.mock import AsyncMock, MagicMock

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
    """When COMPOSIO_API_KEY is empty, status() must report Composio as
    unavailable and resolve the effective default to in-house."""
    original_key = settings.COMPOSIO_API_KEY
    original_default = settings.CONNECTOR_DEFAULT_BROKER
    settings.COMPOSIO_API_KEY = ""
    try:
        # Force a fresh composio client attempt
        from app.connectors.brokers.composio import composio_broker

        composio_broker._attempted = False
        composio_broker._available = False
        composio_broker._client = None

        status = broker_router.status()
        assert status.default_broker == settings.CONNECTOR_DEFAULT_BROKER
        assert status.composio_configured is False
        assert status.composio_available is False
        assert status.effective_default == BrokerType.IN_HOUSE.value
    finally:
        settings.COMPOSIO_API_KEY = original_key
        settings.CONNECTOR_DEFAULT_BROKER = original_default


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
