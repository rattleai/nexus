"""Celery tasks for async BOM resolution and bulk operations."""

import uuid

import structlog

from app.workers.celery_app import celery_app

logger = structlog.stdlib.get_logger()


@celery_app.task(name="configurator.resolve_bom_async", bind=True, max_retries=2)
def resolve_bom_async(self, session_id: str, tenant_id: str) -> dict:
    """Async BOM resolution for large BOMs via Celery.

    Use this for BOMs with 500+ items where synchronous resolution
    may exceed request timeout.
    """
    import asyncio

    from app.apps.cpq.engine.bom_resolver import BOMResolver
    from app.db.session import get_session

    async def _resolve():
        resolver = BOMResolver()
        async for db in get_session():
            try:
                result = await resolver.resolve(db, uuid.UUID(session_id))
                return {
                    "configured_bom_id": str(result.id),
                    "total_components": result.total_components,
                    "total_cost": str(result.total_cost) if result.total_cost else None,
                    "resolution_duration_ms": result.resolution_duration_ms,
                }
            except Exception as exc:
                logger.error("bom_resolution_failed", session_id=session_id, error=str(exc))
                raise self.retry(exc=exc, countdown=5)

    return asyncio.run(_resolve())


@celery_app.task(name="configurator.bulk_validate_sessions", bind=True)
def bulk_validate_sessions(self, product_id: str, tenant_id: str) -> dict:
    """Re-validate all in-progress sessions for a product.

    Useful after constraint rules are modified.
    """
    import asyncio

    from sqlalchemy import select

    from app.apps.cpq.engine.validator import ConfigurationValidator
    from app.apps.cpq.models.configurator import ConfigurationSession, ConfigurationStatus
    from app.db.session import get_session

    async def _validate():
        validator = ConfigurationValidator()
        updated = 0
        async for db in get_session():
            result = await db.execute(
                select(ConfigurationSession).where(
                    ConfigurationSession.product_id == uuid.UUID(product_id),
                    ConfigurationSession.tenant_id == uuid.UUID(tenant_id),
                    ConfigurationSession.status == ConfigurationStatus.IN_PROGRESS,
                )
            )
            sessions = result.scalars().all()
            for session in sessions:
                await validator.validate(db, session.id)
                updated += 1
            await db.commit()
        return {"validated": updated}

    return asyncio.run(_validate())
