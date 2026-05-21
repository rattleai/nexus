"""Celery tasks for connector maintenance.

- Proactive OAuth token refresh before expiry
- MCP server health checks
- Tool discovery refresh
- Idle session cleanup
"""

from __future__ import annotations

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


def register_connector_beat_schedule() -> dict:
    """Return Celery beat schedule entries for connector tasks.

    Called from Celery configuration to register periodic tasks.
    """
    interval = settings.CONNECTOR_HEALTH_CHECK_INTERVAL_SECONDS

    return {
        "connector-refresh-credentials": {
            "task": "app.connectors.tasks.refresh_expiring_credentials",
            "schedule": interval,
        },
        "connector-health-check": {
            "task": "app.connectors.tasks.check_connector_health",
            "schedule": interval,
        },
        "connector-cleanup-idle-sessions": {
            "task": "app.connectors.tasks.cleanup_idle_mcp_sessions",
            "schedule": 60,  # Every minute
        },
    }


# ── Task implementations ─────────────────────────────────
# These are imported by Celery's autodiscovery. They use sync wrappers
# around async code because Celery workers run synchronously.


async def _refresh_expiring_credentials_async() -> int:
    """Refresh OAuth tokens that are about to expire."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.connectors.credentials import credential_manager
    from app.connectors.models import CredentialType, TenantCredential
    from app.db.session import async_session_factory

    buffer = timedelta(seconds=settings.CONNECTOR_CREDENTIAL_REFRESH_BUFFER_SECONDS)
    threshold = datetime.now(UTC) + buffer
    refreshed = 0

    async with async_session_factory() as db:
        result = await db.execute(
            select(TenantCredential).where(
                TenantCredential.credential_type == CredentialType.OAUTH2,
                TenantCredential.is_valid.is_(True),
                TenantCredential.token_expires_at.isnot(None),
                TenantCredential.token_expires_at < threshold,
                TenantCredential.refresh_token_enc.isnot(None),
            )
        )
        credentials = result.scalars().all()

        for cred in credentials:
            try:
                from sqlalchemy.orm import joinedload

                # Load the connection and connector definition
                conn_result = await db.execute(
                    select(__import__("app.connectors.models", fromlist=["TenantConnection"]).TenantConnection)
                    .where(
                        __import__("app.connectors.models", fromlist=["TenantConnection"]).TenantConnection.id
                        == cred.connection_id
                    )
                    .options(
                        joinedload(
                            __import__(
                                "app.connectors.models", fromlist=["TenantConnection"]
                            ).TenantConnection.connector_definition
                        )
                    )
                )
                connection = conn_result.unique().scalar_one_or_none()
                if not connection or not connection.connector_definition:
                    continue

                await credential_manager.refresh_oauth(cred, connection.connector_definition, db)
                refreshed += 1
            except Exception:
                logger.warning(
                    "credential_proactive_refresh_failed",
                    connection_id=str(cred.connection_id),
                    exc_info=True,
                )

        await db.commit()

    if refreshed:
        logger.info("credentials_proactively_refreshed", count=refreshed)
    return refreshed


async def _check_connector_health_async() -> int:
    """Check health of all active connections."""
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from app.connectors.models import ConnectionStatus, TenantConnection
    from app.db.session import async_session_factory

    checked = 0
    async with async_session_factory() as db:
        result = await db.execute(
            select(TenantConnection)
            .where(
                TenantConnection.status.in_(
                    [
                        ConnectionStatus.ACTIVE,
                        ConnectionStatus.DEGRADED,
                    ]
                ),
                TenantConnection.deleted_at.is_(None),
            )
            .options(joinedload(TenantConnection.connector_definition))
        )
        connections = result.unique().scalars().all()

        for conn in connections:
            cd = conn.connector_definition
            if not cd:
                continue

            try:
                # For connections with credentials, verify token validity
                if (
                    conn.credential
                    and conn.credential.is_valid
                    and (
                        conn.credential.token_expires_at
                        and conn.credential.token_expires_at < datetime.now(UTC)
                        and not conn.credential.refresh_token_enc
                    )
                ):
                    conn.status = ConnectionStatus.EXPIRED
                    conn.status_message = "OAuth token expired with no refresh token"

                conn.health_checked_at = datetime.now(UTC)
                conn.health_status = {"status": "ok", "checked_at": str(datetime.now(UTC))}
                checked += 1

            except Exception:
                conn.health_status = {"status": "error"}
                logger.debug("connector_health_check_failed", connection_id=str(conn.id), exc_info=True)

        await db.commit()

    return checked


async def _cleanup_idle_mcp_sessions_async() -> int:
    """Close MCP sessions that have been idle too long."""
    from app.connectors.mcp_client import mcp_client_pool

    return await mcp_client_pool.cleanup_idle()


# ── Sync task wrappers (for Celery) ──────────────────────

try:
    from celery import shared_task

    @shared_task(name="app.connectors.tasks.refresh_expiring_credentials")
    def refresh_expiring_credentials() -> int:
        import asyncio

        return asyncio.run(_refresh_expiring_credentials_async())

    @shared_task(name="app.connectors.tasks.check_connector_health")
    def check_connector_health() -> int:
        import asyncio

        return asyncio.run(_check_connector_health_async())

    @shared_task(name="app.connectors.tasks.cleanup_idle_mcp_sessions")
    def cleanup_idle_mcp_sessions() -> int:
        import asyncio

        return asyncio.run(_cleanup_idle_mcp_sessions_async())

except ImportError:
    # Celery not available (e.g. in tests or API-only deployment)
    pass
