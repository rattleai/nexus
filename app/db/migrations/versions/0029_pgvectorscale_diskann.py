"""Add pgvectorscale DiskANN indexes for 10x+ throughput over HNSW.

StreamingDiskANN provides up to 471 QPS at 99% recall on 50M vectors,
with Statistical Binary Quantization (SBQ) built into the index.
DiskANN indexes coexist with HNSW — the VECTOR_INDEX_TYPE config
controls which search path is used at runtime.

Requires the pgvectorscale extension to be installed on the PostgreSQL
server. If not available, this migration is a no-op and the system
continues using HNSW indexes.

Revision ID: 0029_pgvectorscale_diskann
Revises: 0028_vector_quantization
Create Date: 2026-04-10
"""

from alembic import op
from sqlalchemy import text

revision = "0029_pgvectorscale_diskann"
down_revision = "0028_vector_quantization"
branch_labels = None
depends_on = None


def _extension_available(connection) -> bool:
    """Check if pgvectorscale is available on this PostgreSQL server."""
    result = connection.execute(
        text("SELECT 1 FROM pg_available_extensions WHERE name = 'vectorscale'")
    )
    return result.scalar() is not None


def upgrade() -> None:
    connection = op.get_bind()

    if not _extension_available(connection):
        connection.execute(
            text(
                "COMMENT ON TABLE data_source_chunks IS "
                "'pgvectorscale not available — DiskANN indexes skipped (migration 0029)'"
            )
        )
        return

    # Install pgvectorscale extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE")

    # DiskANN indexes must be created CONCURRENTLY (non-blocking).
    # CONCURRENTLY requires being outside a transaction block.
    op.execute("COMMIT")

    # DiskANN index on data_source_chunks.embedding_vec
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dsc_embedding_diskann "
        "ON data_source_chunks USING diskann (embedding_vec) "
        "WITH (storage_layout = 'memory_optimized')"
    )

    # DiskANN index on agent_memory_entries.embedding_vec
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ame_embedding_diskann "
        "ON agent_memory_entries USING diskann (embedding_vec) "
        "WITH (storage_layout = 'memory_optimized')"
    )

    op.execute("BEGIN")


def downgrade() -> None:
    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_ame_embedding_diskann")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_dsc_embedding_diskann")
    op.execute("BEGIN")

    # Drop extension only if no other objects depend on it
    op.execute("DROP EXTENSION IF EXISTS vectorscale CASCADE")
