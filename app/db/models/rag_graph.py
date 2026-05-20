"""Knowledge graph models for Graph RAG.

Stores entities and relationships extracted from documents to enable
relationship-aware retrieval (e.g., "Which products are mentioned
alongside Product X?").
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.datasource import VectorType


class RAGEntity(TimestampMixin, Base):
    """An entity extracted from documents (person, product, concept, etc.)."""

    __tablename__ = "rag_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_vec: Mapped[list | None] = mapped_column(VectorType(1536), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (Index("ix_rag_entities_tenant_name_type", "tenant_id", "name", "entity_type", unique=True),)


class RAGRelationship(TimestampMixin, Base):
    """A relationship between two entities."""

    __tablename__ = "rag_relationships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    target_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(100), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (
        Index("ix_rag_relationships_source", "tenant_id", "source_entity_id"),
        Index("ix_rag_relationships_target", "tenant_id", "target_entity_id"),
    )
