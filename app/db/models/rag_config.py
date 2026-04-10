"""Per-tenant RAG configuration model.

Allows tenants to customize their RAG pipeline: embedding model,
chunking strategy, reranker, and feature toggles. Falls back to
global defaults from app.config.settings when not set.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TenantRAGConfig(TimestampMixin, Base):
    """Per-tenant RAG configuration overrides."""

    __tablename__ = "tenant_rag_configs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        primary_key=True,
    )

    # Embedding settings
    embedding_model: Mapped[str] = mapped_column(
        String(100), default="text-embedding-3-small"
    )
    embedding_dimensions: Mapped[int] = mapped_column(Integer, default=1536)

    # Chunking settings
    chunking_strategy: Mapped[str] = mapped_column(
        String(50), default="fixed_size"
    )
    chunk_size: Mapped[int] = mapped_column(Integer, default=1000)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=200)

    # Reranker settings
    reranker_provider: Mapped[str] = mapped_column(String(50), default="none")
    reranker_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Feature toggles
    contextual_retrieval_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_child_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    query_routing_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    hyde_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    graph_rag_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_tenant_rag_configs_tenant", "tenant_id"),
    )
