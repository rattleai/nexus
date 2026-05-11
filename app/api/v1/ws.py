"""WebSocket endpoint for real-time bidirectional communication.

Authentication via query parameter token (WebSocket can't use Authorization header).
Supports heartbeat (server ping every 30s) and event-based messaging.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import jwt
import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.config import settings
from app.core.websocket import manager

logger = structlog.stdlib.get_logger()

router = APIRouter(tags=["websocket"])

HEARTBEAT_INTERVAL = 30  # seconds
HEARTBEAT_TIMEOUT = 10  # seconds


async def _authenticate_ws(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Validate JWT token and return (user_id, tenant_id) or None."""
    if not settings.AUTH_ENABLED:
        return None

    try:
        from app.core.security import decode_access_token

        payload = decode_access_token(token)
        user_id_str = payload.get("sub")
        tenant_id_str = payload.get("tenant_id")
        if not user_id_str or not tenant_id_str:
            return None
        return uuid.UUID(user_id_str), uuid.UUID(tenant_id_str)
    except (jwt.InvalidTokenError, ValueError):
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    token: str = Query("", description="JWT access token for authentication"),
) -> None:
    """WebSocket endpoint for real-time events.

    Events:
    - notification: New notification for the user
    - job_update: Job status change in the tenant
    - presence: User presence updates
    - sync: Data sync events
    - ping/pong: Heartbeat
    """
    # Authenticate
    auth_result = await _authenticate_ws(token) if token else None
    if auth_result is None and settings.AUTH_ENABLED:
        await ws.close(code=4001, reason="Authentication required")
        return

    if auth_result:
        user_id, tenant_id = auth_result
    else:
        # Anonymous connection (AUTH_ENABLED=false) — use zero UUIDs
        user_id = uuid.UUID(int=0)
        tenant_id = uuid.UUID(int=0)

    conn_id = await manager.connect(ws, user_id, tenant_id)

    try:
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(_heartbeat(ws))

        try:
            while True:
                data = await ws.receive_json()
                msg_type = data.get("type", "")

                if msg_type == "ping":
                    await ws.send_json({"type": "pong"})
                # Future: handle client-initiated events here

        except WebSocketDisconnect:
            pass
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
    finally:
        await manager.disconnect(conn_id)


async def _heartbeat(ws: WebSocket) -> None:
    """Send periodic pings to detect dead connections."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await ws.send_json({"type": "ping"})
            except Exception:
                break
    except asyncio.CancelledError:
        pass
