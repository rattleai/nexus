"""Broker router (P2.4).

Dispatches connector operations to the correct broker based on
``ConnectorDefinition.broker``. When a connector is configured for
Composio but the SDK is not installed / no API key is set, the router
transparently falls back to the in-house broker — letting teams adopt
Composio incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.config import settings
from app.connectors.brokers.base import CredentialBroker
from app.connectors.brokers.composio import composio_broker
from app.connectors.brokers.in_house import in_house_broker
from app.connectors.models import BrokerType, ConnectorDefinition

logger = structlog.stdlib.get_logger()


@dataclass(frozen=True)
class BrokerStatus:
    """Operational snapshot of broker availability."""

    default_broker: str
    composio_configured: bool
    composio_available: bool
    in_house_available: bool
    effective_default: str

    def to_dict(self) -> dict[str, object]:
        return {
            "default_broker": self.default_broker,
            "composio_configured": self.composio_configured,
            "composio_available": self.composio_available,
            "in_house_available": self.in_house_available,
            "effective_default": self.effective_default,
        }


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

    def status(self) -> BrokerStatus:
        """Return a snapshot of which brokers are configured + available.

        Useful for /health, admin UIs, and startup diagnostics. Never
        leak this to end users — it exposes internal architecture.
        """
        composio_available = composio_broker.is_available()
        default = settings.CONNECTOR_DEFAULT_BROKER
        if default == BrokerType.COMPOSIO.value and not composio_available:
            effective = BrokerType.IN_HOUSE.value
        else:
            effective = default
        return BrokerStatus(
            default_broker=default,
            composio_configured=bool(settings.COMPOSIO_API_KEY),
            composio_available=composio_available,
            in_house_available=True,
            effective_default=effective,
        )

    def log_startup_status(self) -> None:
        """Emit a structured log line with the current broker posture.

        Warns when the configured default is Composio but the SDK / API key
        is unavailable — that's the classic silent-fallback footgun.
        """
        s = self.status()
        if (
            s.default_broker == BrokerType.COMPOSIO.value
            and not s.composio_available
        ):
            logger.warning(
                "connector_broker_composio_unavailable",
                default_broker=s.default_broker,
                effective=s.effective_default,
                configured=s.composio_configured,
                hint=(
                    "CONNECTOR_DEFAULT_BROKER is 'composio' but the broker is "
                    "unavailable (missing COMPOSIO_API_KEY or composio-core). "
                    "Connectors will silently fall back to in_house."
                ),
            )
        else:
            logger.info(
                "connector_broker_status",
                default_broker=s.default_broker,
                effective=s.effective_default,
                composio_available=s.composio_available,
                composio_configured=s.composio_configured,
            )


broker_router = BrokerRouter()
