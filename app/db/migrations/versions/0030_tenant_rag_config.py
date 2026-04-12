"""Add per-tenant RAG configuration table.

Allows tenants to customize their RAG pipeline independently:
embedding model, chunking strategy, reranker, and feature toggles.
Falls back to global defaults when no tenant-specific config exists.

Revision ID: 0030_tenant_rag_config
Revises: 0029_pgvectorscale_diskann
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0030_tenant_rag_config"
down_revision = "0029_pgvectorscale_diskann"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_rag_configs",
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("embedding_model", sa.String(100), nullable=False, server_default="text-embedding-3-small"),
        sa.Column("embedding_dimensions", sa.Integer, nullable=False, server_default="1536"),
        sa.Column("chunking_strategy", sa.String(50), nullable=False, server_default="fixed_size"),
        sa.Column("chunk_size", sa.Integer, nullable=False, server_default="1000"),
        sa.Column("chunk_overlap", sa.Integer, nullable=False, server_default="200"),
        sa.Column("reranker_provider", sa.String(50), nullable=False, server_default="none"),
        sa.Column("reranker_model", sa.String(100), nullable=True),
        sa.Column("contextual_retrieval_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("parent_child_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("query_routing_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("hyde_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("graph_rag_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_tenant_rag_configs_tenant", "tenant_rag_configs", ["tenant_id"])

    # Enable Row-Level Security
    op.execute("ALTER TABLE tenant_rag_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_rag_configs FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY tenant_isolation ON tenant_rag_configs
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_rag_configs")
    op.drop_table("tenant_rag_configs")
