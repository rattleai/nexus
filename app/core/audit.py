"""Immutable audit logging system for compliance (SOC2, GDPR).

Provides a structured, append-only audit trail of all data access and mutations.
Audit events are written to the database and optionally dispatched via the event system.

Usage:
    from app.core.audit import emit_audit_event, AuditAction

    await emit_audit_event(
        db=db,
        action=AuditAction.CREATE,
        resource_type="job",
        resource_id=str(job.id),
        tenant_id=tenant.id,
        actor_id=str(user.id),
        actor_type="user",
        ip_address=request.client.host,
        changes={"status": ["pending", "processing"]},
    )
"""

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.stdlib.get_logger()


class AuditAction(enum.StrEnum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"
    REGISTER = "register"
    INVITE = "invite"
    REVOKE = "revoke"
    EXPORT = "export"
    UPLOAD = "upload"
    DOWNLOAD = "download"


async def emit_audit_event(
    db: AsyncSession,
    *,
    action: AuditAction,
    resource_type: str,
    resource_id: str | None = None,
    tenant_id: uuid.UUID | None = None,
    actor_id: str | None = None,
    actor_type: str = "user",
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write an immutable audit log entry.

    This is intentionally fire-and-forget for the caller — audit log writes
    should not block or fail the primary operation. Errors are logged but not raised.
    """
    from app.db.models import AuditLog

    try:
        entry = AuditLog(
            action=action.value,
            resource_type=resource_type,
            resource_id=resource_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type=actor_type,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            changes=changes,
            metadata_=metadata,
            occurred_at=datetime.now(UTC),
        )
        db.add(entry)
        # Don't commit here — let the caller's transaction include the audit log.
        # If the caller rolls back, the audit log rolls back too (which is correct:
        # we don't want to audit an action that didn't actually happen).
    except Exception:
        logger.error("audit_log_write_failed", action=action.value, resource_type=resource_type, exc_info=True)


def get_client_ip(request) -> str:
    """Extract client IP from request.

    Uses the direct connection IP (request.client.host) which is reliable.
    X-Real-IP is only trusted when set by a known reverse proxy. Since we
    cannot validate the proxy here, we prefer the direct connection IP and
    log X-Real-IP as supplementary info when available.
    """
    direct_ip = request.client.host if request.client else "unknown"
    # If behind a trusted proxy, X-Real-IP may be more accurate, but we
    # always have the direct IP as a fallback to prevent spoofing.
    forwarded_ip = request.headers.get("X-Real-IP", "").strip()
    if forwarded_ip and forwarded_ip != direct_ip:
        # Log both for forensic purposes; return direct IP as the canonical one
        # unless the connection is from localhost (common proxy setup)
        if direct_ip in ("127.0.0.1", "::1"):
            return forwarded_ip
    return direct_ip
