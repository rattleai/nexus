"""Partition data_source_chunks by tenant_id for scalable multi-tenant vector search.

Hash-partitions data_source_chunks into 16 partitions by tenant_id.
This provides partition pruning on tenant-scoped queries, reducing the
index scan surface per tenant. Combined with RLS for defense-in-depth.

Strategy:
  1. Create new partitioned table with identical schema
  2. Create 16 hash partitions
  3. Copy data from original table
  4. Atomic rename: original → _legacy, partitioned → original
  5. Recreate all indexes, RLS policies, and triggers on partitioned table
  6. Keep _legacy table for 7-day rollback window

IMPORTANT: This migration MUST be tested on staging with production-scale
data before running in production. Run during a maintenance window.

Revision ID: 0031_partition_chunks_by_tenant
Revises: 0030_tenant_rag_config
Create Date: 2026-04-10
"""

from alembic import op

revision = "0031_partition_chunks_by_tenant"
down_revision = "0030_tenant_rag_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Step 1: Create partitioned table with same schema ──────
    op.execute("""
        CREATE TABLE data_source_chunks_partitioned (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            data_source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding JSONB,
            embedding_model VARCHAR(100),
            section_title VARCHAR(500),
            table_index INTEGER,
            embedding_vec vector(1536),
            embedding_halfvec halfvec(1536),
            content_tsv tsvector,
            tags JSONB NOT NULL DEFAULT '[]',
            content_type VARCHAR(50),
            indexed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, tenant_id)
        ) PARTITION BY HASH (tenant_id)
    """)

    # ── Step 2: Create 16 hash partitions ──────────────────────
    for i in range(16):
        op.execute(
            f"CREATE TABLE data_source_chunks_p{i:02d} "
            f"PARTITION OF data_source_chunks_partitioned "
            f"FOR VALUES WITH (MODULUS 16, REMAINDER {i})"
        )

    # ── Step 3: Copy data ──────────────────────────────────────
    op.execute("""
        INSERT INTO data_source_chunks_partitioned
            (id, tenant_id, data_source_id, chunk_index, content, embedding,
             embedding_model, section_title, table_index, embedding_vec,
             embedding_halfvec, content_tsv, tags, content_type, indexed_at,
             created_at, updated_at)
        SELECT id, tenant_id, data_source_id, chunk_index, content, embedding,
               embedding_model, section_title, table_index, embedding_vec,
               embedding_halfvec, content_tsv, tags, content_type, indexed_at,
               created_at, updated_at
        FROM data_source_chunks
    """)

    # ── Step 4: Atomic rename ──────────────────────────────────
    op.execute("ALTER TABLE data_source_chunks RENAME TO data_source_chunks_legacy")
    op.execute("ALTER TABLE data_source_chunks_partitioned RENAME TO data_source_chunks")

    # ── Step 5: Recreate indexes on partitioned table ──────────
    # B-tree indexes (inherited by partitions automatically)
    op.execute(
        "CREATE INDEX ix_dsc_part_tenant ON data_source_chunks (tenant_id)"
    )
    op.execute(
        "CREATE INDEX ix_dsc_part_tenant_source ON data_source_chunks (tenant_id, data_source_id)"
    )
    op.execute(
        "CREATE INDEX ix_dsc_part_tenant_type ON data_source_chunks (tenant_id, content_type)"
    )
    op.execute(
        "CREATE INDEX ix_dsc_part_tenant_indexed ON data_source_chunks (tenant_id, indexed_at)"
    )

    # GIN index for full-text search
    op.execute(
        "CREATE INDEX ix_dsc_part_content_tsv ON data_source_chunks USING gin (content_tsv)"
    )

    # HNSW vector indexes (created on each partition for locality)
    op.execute("COMMIT")

    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dsc_part_embedding_vec "
        "ON data_source_chunks USING hnsw (embedding_vec vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dsc_part_embedding_halfvec "
        "ON data_source_chunks USING hnsw (embedding_halfvec halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    op.execute("BEGIN")

    # ── Step 6: Recreate RLS policies ──────────────────────────
    op.execute("ALTER TABLE data_source_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE data_source_chunks FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY tenant_isolation ON data_source_chunks
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # ── Step 7: Recreate tsvector trigger ──────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION dsc_tsvector_update() RETURNS trigger AS $$
        BEGIN
            NEW.content_tsv := to_tsvector('english', COALESCE(NEW.content, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER dsc_tsvector_trigger
        BEFORE INSERT OR UPDATE OF content ON data_source_chunks
        FOR EACH ROW EXECUTE FUNCTION dsc_tsvector_update()
    """)


def downgrade() -> None:
    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS dsc_tsvector_trigger ON data_source_chunks")

    # Drop RLS
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON data_source_chunks")

    # Reverse rename: drop partitioned, restore legacy
    op.execute("DROP TABLE IF EXISTS data_source_chunks CASCADE")
    op.execute("ALTER TABLE data_source_chunks_legacy RENAME TO data_source_chunks")
