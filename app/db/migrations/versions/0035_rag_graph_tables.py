"""Add knowledge graph tables for Graph RAG.

Stores entities and relationships extracted from documents for
relationship-aware retrieval.

Revision ID: 0035_rag_graph_tables
Revises: 0034_materialized_views_and_ab
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0035_rag_graph_tables"
down_revision = "0034_materialized_views_and_ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Entities ───────────────────────────────────────────────
    op.create_table(
        "rag_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_entities_tenant_name_type",
        "rag_entities",
        ["tenant_id", "name", "entity_type"],
        unique=True,
    )

    # Add vector column for entity embeddings
    op.execute(
        "ALTER TABLE rag_entities ADD COLUMN embedding_vec vector(1536)"
    )

    # ── Relationships ──────────────────────────────────────────
    op.create_table(
        "rag_relationships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(100), nullable=False),
        sa.Column("weight", sa.Float, server_default="1.0"),
        sa.Column("chunk_id", UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rag_relationships_source", "rag_relationships", ["tenant_id", "source_entity_id"])
    op.create_index("ix_rag_relationships_target", "rag_relationships", ["tenant_id", "target_entity_id"])
    op.create_index("ix_rag_relationships_chunk", "rag_relationships", ["chunk_id"])

    # ── Enable RLS ─────────────────────────────────────────────
    for table in ["rag_entities", "rag_relationships"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """)


def downgrade() -> None:
    for table in ["rag_relationships", "rag_entities"]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
