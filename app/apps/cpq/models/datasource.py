"""Data source models: uploads, cloud drives, URLs, and extraction provenance."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
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


class CloudProvider(enum.StrEnum):
    GOOGLE_DRIVE = "google_drive"
    DROPBOX = "dropbox"
    ONEDRIVE = "onedrive"


# ── Cloud Connection ────────────────────────────────────


class CloudConnection(SoftDeleteMixin, AuditMixin, TimestampMixin, Base):
    """OAuth connection to a cloud storage provider, scoped to a tenant."""

    __tablename__ = "cloud_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    provider: Mapped[CloudProvider] = mapped_column(
        Enum(CloudProvider, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    account_email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    data_sources: Mapped[list[DataSource]] = relationship(back_populates="cloud_connection")

    __table_args__ = (
        Index("ix_cloud_connections_tenant", "tenant_id"),
        Index("ix_cloud_connections_tenant_provider", "tenant_id", "provider"),
    )


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

    # Cloud drive info
    cloud_provider: Mapped[CloudProvider | None] = mapped_column(
        Enum(CloudProvider, values_callable=lambda e: [m.value for m in e], create_constraint=False),
        nullable=True,
    )
    cloud_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cloud_connections.id"), nullable=True, index=True
    )
    cloud_file_id: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Extraction results
    extraction_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    # Relationships
    cloud_connection: Mapped[CloudConnection | None] = relationship(back_populates="data_sources")
    chunks: Mapped[list[DataSourceChunk]] = relationship(
        back_populates="data_source", cascade="all, delete-orphan"
    )
    provenance_records: Mapped[list[ConfigItemProvenance]] = relationship(
        back_populates="data_source", cascade="all, delete-orphan"
    )

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


# ── Config Item Provenance ───────────────────────────────


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

    # Relationships
    data_source: Mapped[DataSource] = relationship(back_populates="provenance_records")

    __table_args__ = (
        Index("ix_config_provenance_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_config_provenance_tenant_source", "tenant_id", "data_source_id"),
    )
