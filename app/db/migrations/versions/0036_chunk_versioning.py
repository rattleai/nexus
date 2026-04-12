"""Add content_hash and deleted_at to data_source_chunks for versioning.

Enables incremental re-indexing (skip unchanged chunks via content_hash)
and orphaned vector prevention (soft-delete old chunks before re-indexing,
hard-delete after success).

Revision ID: 0036_chunk_versioning
Revises: 0035_rag_graph_tables
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0036_chunk_versioning"
down_revision = "0035_rag_graph_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_source_chunks",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "data_source_chunks",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Index for efficient filtering of active (non-deleted) chunks
    op.create_index(
        "ix_dsc_deleted_at",
        "data_source_chunks",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    # Index for incremental re-indexing: find existing chunks by data_source + hash
    op.create_index(
        "ix_dsc_source_content_hash",
        "data_source_chunks",
        ["data_source_id", "content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_dsc_source_content_hash")
    op.drop_index("ix_dsc_deleted_at")
    op.drop_column("data_source_chunks", "deleted_at")
    op.drop_column("data_source_chunks", "content_hash")
