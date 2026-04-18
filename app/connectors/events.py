"""Domain events for the connector system.

Used for cache invalidation and cross-module communication
via the existing ``app.core.events`` infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass
class ConnectionCreated(DomainEvent):
    tenant_id: str = ""
    connection_id: str = ""
    connector_slug: str = ""


@dataclass
class ConnectionRemoved(DomainEvent):
    tenant_id: str = ""
    connection_id: str = ""
    connector_slug: str = ""


@dataclass
class ConnectionStatusChanged(DomainEvent):
    tenant_id: str = ""
    connection_id: str = ""
    old_status: str = ""
    new_status: str = ""


@dataclass
class ConnectionToolsRefreshed(DomainEvent):
    tenant_id: str = ""
    connection_id: str = ""
    connector_slug: str = ""
    tool_count: int = 0


@dataclass
class ConnectorCredentialRefreshed(DomainEvent):
    tenant_id: str = ""
    connection_id: str = ""
    connector_slug: str = ""


@dataclass
class ConnectorCredentialExpired(DomainEvent):
    tenant_id: str = ""
    connection_id: str = ""
    connector_slug: str = ""
