"""Celery task for async data source extraction and vectorization.

Bridges the gap between document upload (DataSource in PENDING status)
and the RAG vector pipeline (DataSourceChunks with embeddings).

Flow: DataSource.PENDING → DocumentProcessor.process() → ContentIndexer.index_extraction()
      → DataSource.READY (with chunked, embedded content searchable via /search)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.workers.celery_app import celery

logger = structlog.stdlib.get_logger()

_sync_engine = create_engine(
    settings.sync_database_url, pool_size=3, max_overflow=5, pool_pre_ping=True, pool_recycle=300,
)
_SyncSession = sessionmaker(_sync_engine)


@celery.task(
    name="app.docprocessor.tasks.extract_datasource",
    bind=True,
    max_retries=3,
    soft_time_limit=300,
    time_limit=330,
)
def extract_datasource(self, datasource_id: str) -> dict:
    """Extract, chunk, embed, and index a data source.

    Called asynchronously after a file upload or URL fetch. Transitions
    the DataSource from PENDING → PROCESSING → READY (or ERROR).

    This is a synchronous Celery task that uses sync SQLAlchemy because
    Celery workers run in a sync context. The embedding generation is
    done via a sync wrapper around the async EmbeddingGateway.
    """
    import asyncio

    from app.db.models.datasource import DataSource, DataSourceStatus

    ds_id = uuid.UUID(datasource_id)

    with _SyncSession() as db:
        ds = db.execute(select(DataSource).where(DataSource.id == ds_id)).scalar_one_or_none()
        if not ds:
            logger.error("extraction_datasource_not_found", datasource_id=datasource_id)
            return {"status": "error", "detail": "DataSource not found"}

        if ds.status not in (DataSourceStatus.PENDING, DataSourceStatus.ERROR):
            logger.info("extraction_skipped", datasource_id=datasource_id, status=ds.status)
            return {"status": "skipped", "detail": f"DataSource is {ds.status}"}

        # Mark as PROCESSING
        db.execute(
            update(DataSource)
            .where(DataSource.id == ds_id)
            .values(status=DataSourceStatus.PROCESSING)
        )
        db.commit()

    try:
        # Run async extraction in a new event loop (Celery workers are sync)
        result = asyncio.run(_extract_async(ds_id))
        return result
    except Exception as exc:
        logger.error("extraction_failed", datasource_id=datasource_id, error=str(exc), exc_info=True)
        with _SyncSession() as db:
            db.execute(
                update(DataSource)
                .where(DataSource.id == ds_id)
                .values(
                    status=DataSourceStatus.ERROR,
                    extraction_error=str(exc)[:2000],
                )
            )
            db.commit()

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10) from exc

        return {"status": "error", "detail": str(exc)[:200]}


async def _extract_async(datasource_id: uuid.UUID) -> dict:
    """Async extraction + indexing pipeline."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker as async_sessionmaker

    from app.db.models.datasource import DataSource, DataSourceStatus
    from app.docprocessor.indexer import ContentIndexer
    from app.docprocessor.processor import DocumentProcessor

    engine = create_async_engine(settings.DATABASE_URL, pool_size=2, max_overflow=3)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        ds = await db.get(DataSource, datasource_id)
        if not ds:
            return {"status": "error", "detail": "DataSource not found"}

        # Step 1: Extract content from the source. process_data_source
        # dispatches on ds.source_type (UPLOAD / URL / CLOUD_DRIVE / PASTE)
        # and, for cloud drives, enriches ds.filename/mime_type/file_size
        # from the actual downloaded file.
        processor = DocumentProcessor()
        extraction = await processor.process_data_source(ds, db=db)

        # Store extraction metadata
        ds.extraction_result = extraction.to_dict()

        # Step 2: Chunk, embed, and index
        indexer = ContentIndexer()
        chunk_count = await indexer.index_extraction(
            extraction=extraction,
            data_source_id=ds.id,
            tenant_id=ds.tenant_id,
            db=db,
        )

        # Step 3: Mark as READY
        ds.status = DataSourceStatus.READY
        ds.chunk_count = chunk_count
        await db.commit()

        logger.info(
            "extraction_completed",
            datasource_id=str(datasource_id),
            chunks=chunk_count,
            source_type=extraction.source_type,
        )

        return {
            "status": "completed",
            "datasource_id": str(datasource_id),
            "chunks": chunk_count,
            "source_type": extraction.source_type,
        }

    await engine.dispose()
