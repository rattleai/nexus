"""Add contextual retrieval and parent-child chunk columns.

Contextual retrieval prepends document-level context to each chunk
before embedding, making chunks self-contained. Reduces retrieval
failure by 49% (Anthropic research).

Parent-child retrieval indexes small child chunks for matching and
returns larger parent chunks for context.

Revision ID: 0032_contextual_retrieval
Revises: 0031_partition_chunks_by_tenant
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0032_contextual_retrieval"
down_revision = "0031_partition_chunks_by_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Contextual retrieval columns ───────────────────────────
    op.execute(
        "ALTER TABLE data_source_chunks "
        "ADD COLUMN IF NOT EXISTS context_preamble TEXT"
    )
    op.execute(
        "ALTER TABLE data_source_chunks "
        "ADD COLUMN IF NOT EXISTS content_with_context TEXT"
    )

    # ── Parent-child retrieval columns ─────────────────────────
    op.execute(
        "ALTER TABLE data_source_chunks "
        "ADD COLUMN IF NOT EXISTS parent_chunk_id UUID"
    )
    op.execute(
        "ALTER TABLE data_source_chunks "
        "ADD COLUMN IF NOT EXISTS chunk_level VARCHAR(20) DEFAULT 'standard'"
    )

    # Index for parent-child lookups (resolve children to parents)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dsc_parent_chunk "
        "ON data_source_chunks (parent_chunk_id) "
        "WHERE parent_chunk_id IS NOT NULL"
    )

    # Index for filtering by chunk level
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dsc_chunk_level "
        "ON data_source_chunks (tenant_id, chunk_level)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_dsc_chunk_level")
    op.execute("DROP INDEX IF EXISTS ix_dsc_parent_chunk")
    op.execute("ALTER TABLE data_source_chunks DROP COLUMN IF EXISTS chunk_level")
    op.execute("ALTER TABLE data_source_chunks DROP COLUMN IF EXISTS parent_chunk_id")
    op.execute("ALTER TABLE data_source_chunks DROP COLUMN IF EXISTS content_with_context")
    op.execute("ALTER TABLE data_source_chunks DROP COLUMN IF EXISTS context_preamble")
