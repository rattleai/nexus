"""Add data source models for AI agent document processing.

Creates tables for:
- cloud_connections: OAuth2 connections to cloud drive providers
- data_sources: Registered data sources (uploads, cloud files, URLs, pastes)
- data_source_chunks: Indexed text chunks for RAG retrieval
- config_item_provenance: Tracks which data source produced which config entity

Revision ID: 0022_datasource_models
Revises: 0021_cardinality_check_constraints
Create Date: 2026-03-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0022_datasource_models"
down_revision = "0021_cardinality_check_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cloud_connections ──
    op.create_table(
        "cloud_connections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("account_email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text, nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text, nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", JSONB, server_default="[]"),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        # Mixins
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
    )
    op.create_index("ix_cloud_connections_tenant_provider", "cloud_connections", ["tenant_id", "provider"])

    # ── data_sources ──
    op.create_table(
        "data_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending", nullable=False),
        # File info
        sa.Column("file_key", sa.String(1024), nullable=True),
        sa.Column("filename", sa.String(500), nullable=True),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("file_size", sa.BigInteger, nullable=True),
        # URL info
        sa.Column("url", sa.Text, nullable=True),
        # Cloud drive info
        sa.Column("cloud_provider", sa.String(50), nullable=True),
        sa.Column("cloud_connection_id", UUID(as_uuid=True), sa.ForeignKey("cloud_connections.id"), nullable=True),
        sa.Column("cloud_file_id", sa.String(500), nullable=True),
        # Extraction results
        sa.Column("extraction_result", JSONB, nullable=True),
        sa.Column("extraction_error", sa.Text, nullable=True),
        sa.Column("chunk_count", sa.Integer, server_default="0", nullable=False),
        # Metadata
        sa.Column("metadata", JSONB, server_default="{}"),
        # Mixins
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
    )
    op.create_index("ix_data_sources_tenant_status", "data_sources", ["tenant_id", "status"])
    op.create_index("ix_data_sources_tenant_type", "data_sources", ["tenant_id", "source_type"])

    # ── data_source_chunks ──
    op.create_table(
        "data_source_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("data_source_id", UUID(as_uuid=True), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", JSONB, nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("section_title", sa.String(500), nullable=True),
        sa.Column("table_index", sa.Integer, nullable=True),
        # Mixins
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_data_source_chunks_tenant_source", "data_source_chunks", ["tenant_id", "data_source_id"])

    # ── config_item_provenance ──
    op.create_table(
        "config_item_provenance",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("data_source_id", UUID(as_uuid=True), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_instance_id", UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Float, server_default="1.0", nullable=False),
        sa.Column("extraction_context", JSONB, nullable=True),
        # Mixins
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_config_provenance_tenant_entity", "config_item_provenance", ["tenant_id", "entity_type", "entity_id"])
    op.create_index("ix_config_provenance_tenant_source", "config_item_provenance", ["tenant_id", "data_source_id"])


def downgrade() -> None:
    op.drop_table("config_item_provenance")
    op.drop_table("data_source_chunks")
    op.drop_table("data_sources")
    op.drop_table("cloud_connections")
