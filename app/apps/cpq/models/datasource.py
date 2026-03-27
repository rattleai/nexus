"""CPQ-specific data source model: configuration item provenance tracking.

Infrastructure data source models (DataSource, DataSourceChunk,
CloudConnection) live in ``app.db.models.datasource``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ConfigItemProvenance(TimestampMixin, Base):
    """Tracks which data source produced a given configuration entity."""

    __tablename__ = "config_item_provenance"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_instance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    extraction_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationship to infrastructure DataSource
    data_source = relationship("DataSource", back_populates="provenance_records")

    __table_args__ = (
        Index("ix_config_provenance_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_config_provenance_tenant_source", "tenant_id", "data_source_id"),
    )
