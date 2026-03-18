"""Periodic Celery tasks — scheduled via Beat.

These tasks handle automated housekeeping: cleanup, cache warming, and usage reporting.
"""

import json
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, select, text, update

from app.config import settings
from app.workers.celery_app import celery
from app.workers.tasks import _SyncSession

logger = structlog.stdlib.get_logger()


@celery.task(name="app.workers.periodic.cleanup_expired_jobs")
def cleanup_expired_jobs() -> dict:
    """Hard-delete soft-deleted jobs older than 30 days."""
    from app.db.models import Job

    cutoff = datetime.now(UTC) - timedelta(days=30)
    with _SyncSession() as db:
        result = db.execute(
            delete(Job).where(Job.deleted_at.isnot(None), Job.deleted_at < cutoff)
        )
        count = result.rowcount
        db.commit()

    logger.info("cleanup_expired_jobs_completed", deleted_count=count, cutoff=cutoff.isoformat())
    return {"deleted": count, "cutoff": cutoff.isoformat()}


@celery.task(name="app.workers.periodic.cleanup_stale_processing")
def cleanup_stale_processing() -> dict:
    """Mark jobs stuck in PROCESSING for >1 hour as FAILED."""
    from app.db.models import Job, JobStatus

    cutoff = datetime.now(UTC) - timedelta(hours=1)
    with _SyncSession() as db:
        result = db.execute(
            update(Job)
            .where(
                Job.status == JobStatus.PROCESSING,
                Job.started_at < cutoff,
                Job.deleted_at.is_(None),
            )
            .values(
                status=JobStatus.FAILED,
                error="Timed out: stuck in PROCESSING for over 1 hour",
                completed_at=datetime.now(UTC),
            )
            .execution_options(synchronize_session=False)
        )
        count = result.rowcount
        db.commit()

    if count > 0:
        logger.warning("cleanup_stale_processing_completed", failed_count=count)
    else:
        logger.info("cleanup_stale_processing_completed", failed_count=0)
    return {"failed": count}


@celery.task(name="app.workers.periodic.cache_warmup")
def cache_warmup() -> dict:
    """Pre-warm cache for active tenants."""
    import redis as sync_redis

    from app.db.models import Tenant

    with _SyncSession() as db:
        tenants = (
            db.execute(select(Tenant).where(Tenant.is_active.is_(True), Tenant.deleted_at.is_(None)))
            .scalars()
            .all()
        )

    r = sync_redis.from_url(settings.REDIS_URL)
    warmed = 0
    try:
        for t in tenants:
            key = f"cache:tenants:{t.id}"
            data = json.dumps(
                {
                    "id": str(t.id),
                    "name": t.name,
                    "slug": t.slug,
                    "plan": t.plan,
                    "is_active": t.is_active,
                },
                default=str,
            )
            r.setex(key, 600, data)
            warmed += 1
    finally:
        r.close()

    logger.info("cache_warmup_completed", tenants_warmed=warmed)
    return {"warmed": warmed}


@celery.task(name="app.workers.periodic.storage_usage_report")
def storage_usage_report() -> dict:
    """Log storage usage per tenant (daily)."""
    from app.db.models import Job, Tenant

    with _SyncSession() as db:
        results = db.execute(
            select(
                Tenant.id,
                Tenant.slug,
                Tenant.plan,
                func.count(Job.id).label("job_count"),
            )
            .join(Job, Job.tenant_id == Tenant.id, isouter=True)
            .where(Tenant.deleted_at.is_(None))
            .group_by(Tenant.id, Tenant.slug, Tenant.plan)
        ).all()

    report = []
    for row in results:
        entry = {
            "tenant_id": str(row[0]),
            "slug": row[1],
            "plan": row[2],
            "job_count": row[3],
        }
        report.append(entry)
        logger.info("storage_usage", **entry)

    logger.info("storage_usage_report_completed", tenant_count=len(report))
    return {"tenants": len(report), "report": report}


@celery.task(name="app.workers.periodic.cleanup_expired_tokens")
def cleanup_expired_tokens() -> dict:
    """Delete expired refresh tokens and email verification tokens.

    Prevents unbounded growth of token tables and removes stale credentials.
    """
    from app.db.models import EmailVerificationToken, RefreshToken

    now = datetime.now(UTC)
    with _SyncSession() as db:
        # Remove expired refresh tokens (expired or revoked older than 7 days)
        revoked_cutoff = now - timedelta(days=7)
        refresh_result = db.execute(
            delete(RefreshToken).where(
                (RefreshToken.expires_at < now)
                | ((RefreshToken.revoked.is_(True)) & (RefreshToken.created_at < revoked_cutoff))
            )
        )
        refresh_count = refresh_result.rowcount

        # Remove expired or used email verification tokens older than 7 days
        token_cutoff = now - timedelta(days=7)
        verification_result = db.execute(
            delete(EmailVerificationToken).where(
                (EmailVerificationToken.expires_at < token_cutoff)
                | ((EmailVerificationToken.used_at.isnot(None)) & (EmailVerificationToken.created_at < token_cutoff))
            )
        )
        verification_count = verification_result.rowcount

        db.commit()

    logger.info(
        "cleanup_expired_tokens_completed",
        refresh_tokens_deleted=refresh_count,
        verification_tokens_deleted=verification_count,
    )
    return {"refresh_tokens": refresh_count, "verification_tokens": verification_count}


def _get_retention_model_map() -> dict:
    """Map resource_type → (Model, date_column) for ORM-based retention."""
    from app.agents.models import AgentInstance
    from app.db.models import AuditLog, Job
    from app.db.models.ai import WalletTransaction

    return {
        "jobs": (Job, Job.completed_at),
        "audit_logs": (AuditLog, AuditLog.occurred_at),
        "agent_instances": (AgentInstance, AgentInstance.completed_at),
        "wallet_transactions": (WalletTransaction, WalletTransaction.created_at),
    }


@celery.task(name="app.workers.periodic.enforce_data_retention")
def enforce_data_retention() -> dict:
    """Enforce data retention policies — archive and/or delete expired data.

    For each active DataRetentionPolicy, counts and deletes records older
    than the retention period using the ORM (no raw SQL).
    """
    from app.db.models.operations import AuditLog, DataRetentionPolicy

    now = datetime.now(UTC)
    total_deleted = 0
    total_archived = 0
    model_map = _get_retention_model_map()

    with _SyncSession() as db:
        policies = db.execute(
            select(DataRetentionPolicy).where(
                DataRetentionPolicy.is_active.is_(True),
            )
        ).scalars().all()

        for policy in policies:
            resource = policy.resource_type
            if resource not in model_map:
                logger.warning("retention_unknown_resource", resource_type=resource)
                continue

            model_cls, date_col = model_map[resource]
            cutoff = now - timedelta(days=policy.retention_days)

            try:
                # Count via ORM
                count_result = db.execute(
                    select(func.count()).select_from(model_cls).where(
                        model_cls.tenant_id == policy.tenant_id,
                        date_col < cutoff,
                    )
                )
                count = count_result.scalar() or 0

                if count == 0:
                    continue

                if policy.archive_before_delete and resource != "audit_logs":
                    archive_entry = AuditLog(
                        tenant_id=policy.tenant_id,
                        actor_type="system",
                        action="data_retention_archive",
                        resource_type=resource,
                        changes={"records_archived": count, "cutoff": cutoff.isoformat()},
                        metadata_={"policy_id": str(policy.id), "retention_days": policy.retention_days},
                    )
                    db.add(archive_entry)
                    total_archived += count

                # Delete via ORM
                db.execute(
                    delete(model_cls).where(
                        model_cls.tenant_id == policy.tenant_id,
                        date_col < cutoff,
                    )
                )
                total_deleted += count

            except Exception:
                logger.error(
                    "retention_enforcement_failed",
                    resource_type=resource,
                    tenant_id=str(policy.tenant_id),
                    exc_info=True,
                )

        db.commit()

    logger.info(
        "enforce_data_retention_completed",
        total_deleted=total_deleted,
        total_archived=total_archived,
        policies_evaluated=len(policies),
    )
    return {"deleted": total_deleted, "archived": total_archived, "policies": len(policies)}


@celery.task(name="app.workers.periodic.hard_purge_deleted_accounts")
def hard_purge_deleted_accounts() -> dict:
    """Hard-purge soft-deleted accounts older than 30 days.

    GDPR requires that deleted data is actually removed, not just
    soft-deleted indefinitely. This task handles the final cleanup.
    """
    from app.db.models.core import Tenant

    cutoff = datetime.now(UTC) - timedelta(days=30)
    with _SyncSession() as db:
        # Find tenants soft-deleted > 30 days ago
        tenants = db.execute(
            select(Tenant).where(
                Tenant.deleted_at.isnot(None),
                Tenant.deleted_at < cutoff,
            )
        ).scalars().all()

        purged = 0
        for tenant in tenants:
            try:
                # Cascade delete tenant data in order (respecting FK constraints)
                for table in [
                    "agent_memory_entries", "agent_sessions", "agent_instances",
                    "agent_definitions", "workflow_runs", "workflow_definitions",
                    "consents", "data_subject_requests", "data_retention_policies",
                    "jobs", "webhook_deliveries", "webhook_endpoints",
                    "notifications", "invitations", "api_keys",
                ]:
                    db.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                        {"tid": str(tenant.id)},
                    )

                # Finally delete the tenant itself
                db.execute(
                    text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"),
                    {"tid": str(tenant.id)},
                )
                db.execute(
                    text("DELETE FROM tenants WHERE id = :tid"),
                    {"tid": str(tenant.id)},
                )
                purged += 1
            except Exception:
                logger.error("hard_purge_failed", tenant_id=str(tenant.id), exc_info=True)

        db.commit()

    logger.info("hard_purge_deleted_accounts_completed", purged=purged)
    return {"purged": purged}


@celery.task(name="app.workers.periodic.cleanup_expired_invitations")
def cleanup_expired_invitations() -> dict:
    """Mark expired pending invitations as EXPIRED."""
    from app.db.models import Invitation, InvitationStatus

    now = datetime.now(UTC)
    with _SyncSession() as db:
        result = db.execute(
            update(Invitation)
            .where(
                Invitation.status == InvitationStatus.PENDING,
                Invitation.expires_at < now,
            )
            .values(status=InvitationStatus.EXPIRED)
            .execution_options(synchronize_session=False)
        )
        count = result.rowcount
        db.commit()

    if count > 0:
        logger.info("cleanup_expired_invitations_completed", expired_count=count)
    return {"expired": count}
