"""WebSocket connection manager for real-time bidirectional communication.

Supports per-user and per-tenant event broadcasting for notifications,
job updates, presence, and sync events.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from starlette.websockets import WebSocket, WebSocketDisconnect

logger = structlog.stdlib.get_logger()


@dataclass
class Connection:
    ws: WebSocket
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class ConnectionManager:
    """Manages WebSocket connections per user/tenant.

    Thread-safe for concurrent connection/disconnection.
    """

    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}  # ws id -> Connection
        self._user_connections: dict[uuid.UUID, set[str]] = {}  # user_id -> ws ids
        self._tenant_connections: dict[uuid.UUID, set[str]] = {}  # tenant_id -> ws ids
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return len(self._connections)

    async def connect(
        self, ws: WebSocket, user_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> str:
        """Accept and register a WebSocket connection. Returns connection ID."""
        await ws.accept()
        conn_id = str(uuid.uuid4())
        conn = Connection(ws=ws, user_id=user_id, tenant_id=tenant_id)

        async with self._lock:
            self._connections[conn_id] = conn
            self._user_connections.setdefault(user_id, set()).add(conn_id)
            self._tenant_connections.setdefault(tenant_id, set()).add(conn_id)

        logger.info("ws_connected", conn_id=conn_id, user_id=str(user_id))
        return conn_id

    async def disconnect(self, conn_id: str) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            conn = self._connections.pop(conn_id, None)
            if conn is None:
                return
            self._user_connections.get(conn.user_id, set()).discard(conn_id)
            self._tenant_connections.get(conn.tenant_id, set()).discard(conn_id)
            # Clean up empty sets
            if conn.user_id in self._user_connections and not self._user_connections[conn.user_id]:
                del self._user_connections[conn.user_id]
            if conn.tenant_id in self._tenant_connections and not self._tenant_connections[conn.tenant_id]:
                del self._tenant_connections[conn.tenant_id]

        logger.info("ws_disconnected", conn_id=conn_id)

    async def send_personal(self, user_id: uuid.UUID, event: dict[str, Any]) -> int:
        """Send an event to all connections for a specific user. Returns send count."""
        conn_ids = self._user_connections.get(user_id, set()).copy()
        return await self._send_to_connections(conn_ids, event)

    async def broadcast_tenant(self, tenant_id: uuid.UUID, event: dict[str, Any]) -> int:
        """Send an event to all connections in a tenant. Returns send count."""
        conn_ids = self._tenant_connections.get(tenant_id, set()).copy()
        return await self._send_to_connections(conn_ids, event)

    async def broadcast_all(self, event: dict[str, Any]) -> int:
        """Send an event to all connected clients. Returns send count."""
        conn_ids = set(self._connections.keys())
        return await self._send_to_connections(conn_ids, event)

    async def _send_to_connections(
        self, conn_ids: set[str], event: dict[str, Any]
    ) -> int:
        """Send event to a set of connections, removing any that fail."""
        import json

        message = json.dumps(event)
        sent = 0
        failed: list[str] = []

        for conn_id in conn_ids:
            conn = self._connections.get(conn_id)
            if conn is None:
                continue
            try:
                await conn.ws.send_text(message)
                sent += 1
            except Exception:
                failed.append(conn_id)

        # Clean up failed connections
        for conn_id in failed:
            await self.disconnect(conn_id)

        return sent


# Global connection manager instance
manager = ConnectionManager()
