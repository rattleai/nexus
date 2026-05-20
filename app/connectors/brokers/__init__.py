"""Credential brokers for connector execution.

Each broker implements the ``CredentialBroker`` interface and services
OAuth flows + tool invocations for connectors assigned to it. The
``BrokerRouter`` dispatches to the correct broker based on
``ConnectorDefinition.broker`` (``composio`` | ``in_house``).
"""

from app.connectors.brokers.base import (
    AuthorizationStart,
    CredentialBroker,
    ToolDescriptor,
    ToolResult,
)
from app.connectors.brokers.router import broker_router

__all__ = [
    "AuthorizationStart",
    "CredentialBroker",
    "ToolDescriptor",
    "ToolResult",
    "broker_router",
]
