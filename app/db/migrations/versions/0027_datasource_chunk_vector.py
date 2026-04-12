"""Add pgvector column, tsvector, HNSW index, and metadata to data_source_chunks.

Migrates embedding storage from JSONB to native pgvector vector(1536) for
hardware-accelerated similarity search. Adds tsvector for hybrid search
(vector + full-text with RRF). Adds metadata columns for filtering.

Revision ID: 0027_datasource_chunk_vector
Revises: 0026_cpq_rls_with_check
Create Date: 2026-04-07
"""

from alembic import op
import sqlalchemy as sa

revision = "0027_datasource_chunk_vector"
down_revision = "0026_cpq_rls_with_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector extension is installed (idempotent — may already exist
    # from migration 0006)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── Add native vector column ────────────────────────────────
    op.execute(
        "ALTER TABLE data_source_chunks "
        "ADD COLUMN IF NOT EXISTS embedding_vec vector(1536)"
    )

    # Backfill from existing JSONB embedding column (same pattern as 0006)
    op.execute("""
        UPDATE data_source_chunks
        SET embedding_vec = (
            SELECT array_agg(v::float)::vector
            FROM jsonb_array_elements_text(embedding) AS v
        )
        WHERE embedding IS NOT NULL
          AND embedding_vec IS NULL
          AND jsonb_typeof(embedding) = 'array'
          AND jsonb_array_length(embedding) = 1536
    """)

    # ── Add tsvector column for full-text search ────────────────
    op.execute(
        "ALTER TABLE data_source_chunks "
        "ADD COLUMN IF NOT EXISTS content_tsv tsvector"
    )

    # Backfill tsvector from content
    op.execute("""
        UPDATE data_source_chunks
        SET content_tsv = to_tsvector('english', content)
        WHERE content_tsv IS NULL AND content IS NOT NULL
    """)

    # ── Add metadata columns for filtering ──────────────────────
    op.execute(
        "ALTER TABLE data_source_chunks "
        "ADD COLUMN IF NOT EXISTS tags jsonb NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE data_source_chunks "
        "ADD COLUMN IF NOT EXISTS content_type varchar(50)"
    )
    op.execute(
        "ALTER TABLE data_source_chunks "
        "ADD COLUMN IF NOT EXISTS indexed_at timestamptz DEFAULT now()"
    )

    # ── Add trigger to auto-update content_tsv on insert/update ─
    op.execute("""
        CREATE OR REPLACE FUNCTION data_source_chunks_tsv_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.content_tsv := to_tsvector('english', COALESCE(NEW.content, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_data_source_chunks_tsv
        ON data_source_chunks
    """)
    op.execute("""
        CREATE TRIGGER trg_data_source_chunks_tsv
        BEFORE INSERT OR UPDATE OF content
        ON data_source_chunks
        FOR EACH ROW EXECUTE FUNCTION data_source_chunks_tsv_trigger()
    """)

    # ── Create indexes CONCURRENTLY (requires COMMIT) ───────────
    # Same pattern as migration 0006: commit the transaction, create
    # indexes concurrently, then re-enter a transaction.
    op.execute("COMMIT")

    # HNSW index for vector similarity search
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_data_source_chunks_embedding_vec "
        "ON data_source_chunks USING hnsw (embedding_vec vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # GIN index for full-text search
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_data_source_chunks_content_tsv "
        "ON data_source_chunks USING gin (content_tsv)"
    )

    # Composite B-tree indexes for metadata filtering
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_data_source_chunks_tenant_type "
        "ON data_source_chunks (tenant_id, content_type)"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_data_source_chunks_tenant_indexed "
        "ON data_source_chunks (tenant_id, indexed_at)"
    )

    op.execute("BEGIN")


def downgrade() -> None:
    # Drop trigger and function within the Alembic-managed transaction
    op.execute("DROP TRIGGER IF EXISTS trg_data_source_chunks_tsv ON data_source_chunks")
    op.execute("DROP FUNCTION IF EXISTS data_source_chunks_tsv_trigger()")

    # DROP INDEX CONCURRENTLY requires being outside a transaction
    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_data_source_chunks_tenant_indexed")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_data_source_chunks_tenant_type")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_data_source_chunks_content_tsv")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_data_source_chunks_embedding_vec")
    # Re-enter a transaction for remaining DDL
    op.execute("BEGIN")

    op.execute("ALTER TABLE data_source_chunks DROP COLUMN IF EXISTS indexed_at")
    op.execute("ALTER TABLE data_source_chunks DROP COLUMN IF EXISTS content_type")
    op.execute("ALTER TABLE data_source_chunks DROP COLUMN IF EXISTS tags")
    op.execute("ALTER TABLE data_source_chunks DROP COLUMN IF EXISTS content_tsv")
    op.execute("ALTER TABLE data_source_chunks DROP COLUMN IF EXISTS embedding_vec")
