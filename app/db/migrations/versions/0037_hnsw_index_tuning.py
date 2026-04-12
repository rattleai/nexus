"""Rebuild HNSW indexes with improved parameters for better recall.

Previous: m=16, ef_construction=64 (conservative defaults)
New:      m=24, ef_construction=128 (optimized for 1536-dim vectors)

Research shows m=24 provides ~3% recall improvement over m=16 and
ef_construction=128 improves tail recall (p95/p99) by 2-5% for
1536-dimensional embeddings at moderate storage cost (~1.5x index size).

Uses non-concurrent index operations. For zero-downtime production
rebuilds, create the new index CONCURRENTLY manually outside this
migration, then run a separate rename migration. CONCURRENTLY inside
alembic with asyncpg is fragile because alembic's transactional DDL
wrapper conflicts with PostgreSQL's requirement that CONCURRENTLY run
outside any transaction block.

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

_NUM_PARTITIONS = 16


def _drop_if_exists(name: str) -> None:
    op.execute(f"DROP INDEX IF EXISTS {name}")


def _create_hnsw(name: str, table: str, col: str, ops: str, m: int, ef: int) -> None:
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {name} "
        f"ON {table} USING hnsw ({col} {ops}) "
        f"WITH (m = {m}, ef_construction = {ef})"
    )


def _rebuild(name: str, table: str, col: str, ops: str, m: int, ef: int) -> None:
    _drop_if_exists(name)
    _create_hnsw(name, table, col, ops, m, ef)


def upgrade() -> None:
    # data_source_chunks: rebuild HNSW index on each partition
    for i in range(_NUM_PARTITIONS):
        part = f"data_source_chunks_p{i:02d}"
        _rebuild(
            f"ix_dsc_p{i:02d}_embedding_vec", part,
            "embedding_vec", "vector_cosine_ops", _M, _EF_CONSTRUCTION,
        )
        _rebuild(
            f"ix_dsc_p{i:02d}_embedding_halfvec", part,
            "embedding_halfvec", "halfvec_cosine_ops", _M, _EF_CONSTRUCTION,
        )

    # agent_memory_entries: non-partitioned
    _rebuild(
        "ix_agent_memory_embedding_vec", "agent_memory_entries",
        "embedding_vec", "vector_cosine_ops", _M, _EF_CONSTRUCTION,
    )
    _rebuild(
        "ix_agent_memory_embedding_halfvec", "agent_memory_entries",
        "embedding_halfvec", "halfvec_cosine_ops", _M, _EF_CONSTRUCTION,
    )


def downgrade() -> None:
    for i in range(_NUM_PARTITIONS):
        part = f"data_source_chunks_p{i:02d}"
        _rebuild(
            f"ix_dsc_p{i:02d}_embedding_vec", part,
            "embedding_vec", "vector_cosine_ops", 16, 64,
        )
        _rebuild(
            f"ix_dsc_p{i:02d}_embedding_halfvec", part,
            "embedding_halfvec", "halfvec_cosine_ops", 16, 64,
        )
    _rebuild(
        "ix_agent_memory_embedding_vec", "agent_memory_entries",
        "embedding_vec", "vector_cosine_ops", 16, 64,
    )
    _rebuild(
        "ix_agent_memory_embedding_halfvec", "agent_memory_entries",
        "embedding_halfvec", "halfvec_cosine_ops", 16, 64,
    )
