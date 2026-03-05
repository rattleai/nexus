"""Data export Celery tasks — generates tenant/user data archives."""

import json
import uuid

import structlog
from sqlalchemy import select

from app.workers.celery_app import celery
from app.workers.tasks import _SyncSession

logger = structlog.stdlib.get_logger()


@celery.task(name="app.workers.export_tenant_data", bind=True, max_retries=2)
def export_tenant_data(self, tenant_id: str, user_id: str, export_id: str, format: str = "json") -> dict:
    """Export all data for a tenant as a JSON archive."""
    from app.db.models import ApiKey, Job, Tenant, TenantMembership, User

    tid = uuid.UUID(tenant_id)

    with _SyncSession() as db:
        # Load tenant
        tenant = db.execute(select(Tenant).where(Tenant.id == tid)).scalar_one_or_none()
        if not tenant:
            return {"status": "error", "detail": "Tenant not found"}

        # Collect all tenant data
        users = db.execute(
            select(User).where(User.tenant_id == tid, User.deleted_at.is_(None))
        ).scalars().all()

        jobs = db.execute(
            select(Job).where(Job.tenant_id == tid, Job.deleted_at.is_(None))
        ).scalars().all()

        api_keys = db.execute(
            select(ApiKey).where(ApiKey.tenant_id == tid)
        ).scalars().all()

        memberships = db.execute(
            select(TenantMembership).where(TenantMembership.tenant_id == tid)
        ).scalars().all()

    export_data = {
        "export_id": export_id,
        "tenant": {
            "id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "plan": tenant.plan,
            "settings": tenant.settings,
            "created_at": str(tenant.created_at),
        },
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "display_name": u.display_name,
                "created_at": str(u.created_at),
            }
            for u in users
        ],
        "jobs": [
            {
                "id": str(j.id),
                "type": j.type,
                "status": j.status.value,
                "payload": j.payload,
                "result": j.result,
                "created_at": str(j.created_at),
                "completed_at": str(j.completed_at) if j.completed_at else None,
            }
            for j in jobs
        ],
        "api_keys": [
            {
                "id": str(k.id),
                "name": k.name,
                "scopes": k.scopes,
                "active": k.active,
                "created_at": str(k.created_at),
            }
            for k in api_keys
        ],
        "memberships": [
            {
                "user_id": str(m.user_id),
                "role": m.role.value,
                "created_at": str(m.created_at),
            }
            for m in memberships
        ],
    }

    # Store export as JSON in S3
    try:
        from app.storage.s3 import S3Storage

        storage = S3Storage()
        key = f"exports/{tenant_id}/{export_id}.json"
        storage.upload(key, json.dumps(export_data, indent=2, default=str).encode())
        logger.info("tenant_export_completed", export_id=export_id, key=key)

        # TODO: Send email notification with download link
        return {"status": "completed", "key": key}
    except Exception as exc:
        logger.error("tenant_export_failed", export_id=export_id, error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc


@celery.task(name="app.workers.export_user_data", bind=True, max_retries=2)
def export_user_data(self, user_id: str, export_id: str, format: str = "json") -> dict:
    """Export personal data for a single user."""
    from app.db.models import OAuthAccount, TenantMembership, User

    uid = uuid.UUID(user_id)

    with _SyncSession() as db:
        user = db.execute(select(User).where(User.id == uid)).scalar_one_or_none()
        if not user:
            return {"status": "error", "detail": "User not found"}

        memberships = db.execute(
            select(TenantMembership).where(TenantMembership.user_id == uid)
        ).scalars().all()

        oauth_accounts = db.execute(
            select(OAuthAccount).where(OAuthAccount.user_id == uid)
        ).scalars().all()

    export_data = {
        "export_id": export_id,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "email_verified": user.email_verified,
            "created_at": str(user.created_at),
            "last_login_at": str(user.last_login_at) if user.last_login_at else None,
        },
        "memberships": [
            {"tenant_id": str(m.tenant_id), "role": m.role.value}
            for m in memberships
        ],
        "oauth_accounts": [
            {"provider": oa.provider, "provider_user_id": oa.provider_user_id}
            for oa in oauth_accounts
        ],
    }

    try:
        from app.storage.s3 import S3Storage

        storage = S3Storage()
        key = f"exports/users/{user_id}/{export_id}.json"
        storage.upload(key, json.dumps(export_data, indent=2, default=str).encode())
        logger.info("user_export_completed", export_id=export_id, key=key)
        return {"status": "completed", "key": key}
    except Exception as exc:
        logger.error("user_export_failed", export_id=export_id, error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
