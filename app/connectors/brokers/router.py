"""Broker router (P2.4).

Dispatches connector operations to the correct broker based on
``ConnectorDefinition.broker``. When a connector is configured for
Composio but the SDK is not installed / no API key is set, the router
transparently falls back to the in-house broker — letting teams adopt
Composio incrementally.
"""

from __future__ import annotations

import structlog

from app.connectors.brokers.base import CredentialBroker
from app.connectors.brokers.composio import composio_broker
from app.connectors.brokers.in_house import in_house_broker
from app.connectors.models import BrokerType, ConnectorDefinition

logger = structlog.stdlib.get_logger()


class BrokerRouter:
    """Routes to the correct broker implementation for a connector."""

    def __init__(self) -> None:
        self._brokers: dict[str, CredentialBroker] = {
            BrokerType.IN_HOUSE.value: in_house_broker,
            BrokerType.COMPOSIO.value: composio_broker,
        }

    def for_connector(self, connector_def: ConnectorDefinition) -> CredentialBroker:
        """Pick the broker for a connector, with fallback to in-house."""
        broker_key = (
            connector_def.broker.value
            if hasattr(connector_def.broker, "value")
            else str(connector_def.broker)
        )

        if broker_key == BrokerType.COMPOSIO.value:
            if not composio_broker.is_available():
                logger.debug(
                    "broker_router_composio_unavailable_fallback",
                    connector=connector_def.slug,
                )
                return in_house_broker

        return self._brokers.get(broker_key, in_house_broker)


broker_router = BrokerRouter()
