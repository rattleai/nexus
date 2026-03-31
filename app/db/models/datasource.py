"""Infrastructure data source models: uploads, cloud drives, URLs, and chunking.

Application-agnostic — used by docprocessor, agents, and application plugins.
Application-specific models (e.g. ConfigItemProvenance) live in their
respective plugin packages.

Cloud drive connections are now managed by the connector system
(``app.connectors.models.TenantConnection``).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin


# ── Enums ────────────────────────────────────────────────


class DataSourceType(enum.StrEnum):
    UPLOAD = "upload"
    CLOUD_DRIVE = "cloud_drive"
    URL = "url"
    PASTE = "paste"


class DataSourceStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


# ── Data Source ──────────────────────────────────────────


class DataSource(SoftDeleteMixin, AuditMixin, TimestampMixin, Base):
    """A data source (file upload, URL, cloud file, or pasted text) for AI extraction."""

    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[DataSourceType] = mapped_column(
        Enum(DataSourceType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    status: Mapped[DataSourceStatus] = mapped_column(
        Enum(DataSourceStatus, values_callable=lambda e: [m.value for m in e]),
        default=DataSourceStatus.PENDING,
    )

    # File info
    file_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # URL info
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Connector-based cloud drive info (references the unified connector system)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenant_connections.id", ondelete="SET NULL"), nullable=True,
    )
    connector_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cloud_file_id: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Extraction results
    extraction_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    # Relationships
    chunks: Mapped[list[DataSourceChunk]] = relationship(
        back_populates="data_source", cascade="all, delete-orphan"
    )
    # NOTE: provenance_records relationship is contributed by the CPQ plugin
    # (see app.apps.cpq.models.datasource.ConfigItemProvenance)

    __table_args__ = (
        Index("ix_data_sources_tenant", "tenant_id"),
        Index("ix_data_sources_tenant_status", "tenant_id", "status"),
        Index("ix_data_sources_tenant_type", "tenant_id", "source_type"),
    )


# ── Data Source Chunk ────────────────────────────────────


class DataSourceChunk(TimestampMixin, Base):
    """A chunk of extracted content from a data source, with optional embedding."""

    __tablename__ = "data_source_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    table_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    data_source: Mapped[DataSource] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_data_source_chunks_tenant_source", "tenant_id", "data_source_id"),
    )
