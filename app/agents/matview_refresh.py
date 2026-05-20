"""Celery task to refresh materialized views for RAG hot paths.

Refreshes tenant chunk statistics materialized view concurrently
(non-blocking) on a periodic schedule.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text

logger = structlog.stdlib.get_logger()


async def refresh_matviews() -> None:
    """Refresh all RAG-related materialized views."""
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        try:
            await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_tenant_chunk_stats"))
            await session.commit()
            logger.info("matview_refreshed", view="mv_tenant_chunk_stats")
        except Exception:
            logger.warning("matview_refresh_failed", view="mv_tenant_chunk_stats", exc_info=True)
