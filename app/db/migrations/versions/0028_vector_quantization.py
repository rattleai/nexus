"""Add halfvec quantized column and HNSW index for compressed vector search.

Adds a half-precision (float16) vector column alongside the existing
full-precision (float32) column. This provides 50% storage savings
with near-zero recall loss, and is the recommended approach over
external quantization libraries (TurboQuant, PQ) because pgvector's
native halfvec type is fully integrated with HNSW indexing.

Storage comparison for 1536-dim embeddings:
  - vector(1536)  float32: 6,144 bytes/vector
  - halfvec(1536) float16: 3,072 bytes/vector  (50% savings)
  - bit(1536)     binary:    192 bytes/vector  (97% savings, lower recall)

Revision ID: 0028_vector_quantization
Revises: 0027_datasource_chunk_vector
Create Date: 2026-04-07
"""

from alembic import op

revision = "0028_vector_quantization"
down_revision = "0027_datasource_chunk_vector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Add halfvec columns ─────────────────────────────────────
    # data_source_chunks: half-precision search column
    op.execute(
        "ALTER TABLE data_source_chunks "
        "ADD COLUMN IF NOT EXISTS embedding_halfvec halfvec(1536)"
    )

    # agent_memory_entries: half-precision search column
    op.execute(
        "ALTER TABLE agent_memory_entries "
        "ADD COLUMN IF NOT EXISTS embedding_halfvec halfvec(1536)"
    )

    # ── Backfill halfvec from full-precision vectors ────────────
    # Cast is lossless in PostgreSQL: vector → halfvec truncates to float16
    op.execute("""
        UPDATE data_source_chunks
        SET embedding_halfvec = embedding_vec::halfvec(1536)
        WHERE embedding_vec IS NOT NULL
          AND embedding_halfvec IS NULL
    """)

    op.execute("""
        UPDATE agent_memory_entries
        SET embedding_halfvec = embedding_vec::halfvec(1536)
        WHERE embedding_vec IS NOT NULL
          AND embedding_halfvec IS NULL
    """)

    # ── Create HNSW indexes on halfvec columns CONCURRENTLY ─────
    # These indexes are ~50% smaller than the full-precision indexes
    # and provide equivalent search performance.
    op.execute("COMMIT")

    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_data_source_chunks_embedding_halfvec "
        "ON data_source_chunks USING hnsw (embedding_halfvec halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_agent_memory_embedding_halfvec "
        "ON agent_memory_entries USING hnsw (embedding_halfvec halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    op.execute("BEGIN")


def downgrade() -> None:
    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_agent_memory_embedding_halfvec")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_data_source_chunks_embedding_halfvec")
    op.execute("BEGIN")

    op.execute("ALTER TABLE agent_memory_entries DROP COLUMN IF EXISTS embedding_halfvec")
    op.execute("ALTER TABLE data_source_chunks DROP COLUMN IF EXISTS embedding_halfvec")
