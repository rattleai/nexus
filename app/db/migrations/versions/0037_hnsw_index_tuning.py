"""Rebuild HNSW indexes with improved parameters for better recall.

Previous: m=16, ef_construction=64 (conservative defaults)
New:      m=24, ef_construction=128 (optimized for 1536-dim vectors)

Research shows m=24 provides ~3% recall improvement over m=16 and
ef_construction=128 improves tail recall (p95/p99) by 2-5% for
1536-dimensional embeddings at moderate storage cost (~1.5x index size).

Zero-downtime pattern:
  1. CREATE new index CONCURRENTLY with a temporary name (_v2)
  2. Once built, DROP the old index CONCURRENTLY
  3. RENAME the new index back to the original name
This avoids leaving the column unindexed at any point, which would cause
vector queries to fall back to sequential scans during the rebuild window.

Revision ID: 0037_hnsw_index_tuning
Revises: 0036_chunk_versioning
Create Date: 2026-04-10
"""

from alembic import op

revision = "0037_hnsw_index_tuning"
down_revision = "0036_chunk_versioning"
branch_labels = None
depends_on = None

# Tuned parameters for 1536-dim vectors
_M = 24
_EF_CONSTRUCTION = 128

# (table, column, ops_class, final_index_name)
_INDEXES = [
    ("data_source_chunks", "embedding_vec", "vector_cosine_ops", "ix_dsc_part_embedding_vec"),
    ("data_source_chunks", "embedding_halfvec", "halfvec_cosine_ops", "ix_dsc_part_embedding_halfvec"),
    ("agent_memory_entries", "embedding_vec", "vector_cosine_ops", "ix_agent_memory_embedding_vec"),
    ("agent_memory_entries", "embedding_halfvec", "halfvec_cosine_ops", "ix_agent_memory_embedding_halfvec"),
]


def _rebuild(table: str, col: str, ops: str, name: str, m: int, ef: int) -> None:
    """Zero-downtime rebuild: create v2, drop v1, rename v2 -> v1."""
    v2 = f"{name}_v2"
    # 1. Create the new index under a temporary name
    op.execute(
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {v2} "
        f"ON {table} USING hnsw ({col} {ops}) "
        f"WITH (m = {m}, ef_construction = {ef})"
    )
    # 2. Drop the old index (non-blocking)
    op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    # 3. Rename the new index back to the canonical name (metadata-only, fast)
    op.execute(f"ALTER INDEX IF EXISTS {v2} RENAME TO {name}")


def upgrade() -> None:
    # CONCURRENTLY requires being outside a transaction block.
    op.execute("COMMIT")

    for table, col, ops, name in _INDEXES:
        _rebuild(table, col, ops, name, _M, _EF_CONSTRUCTION)

    op.execute("BEGIN")


def downgrade() -> None:
    # Revert to original parameters using the same zero-downtime pattern.
    op.execute("COMMIT")

    for table, col, ops, name in _INDEXES:
        _rebuild(table, col, ops, name, 16, 64)

    op.execute("BEGIN")
