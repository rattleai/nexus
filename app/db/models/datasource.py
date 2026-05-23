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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType


class VectorPrecision(enum.StrEnum):
    """Vector storage precision modes for pgvector columns."""

    FULL = "full"  # float32 vector(N) — 4 bytes/dim
    HALF = "half"  # float16 halfvec(N) — 2 bytes/dim (50% savings)
    BINARY = "binary"  # 1-bit bit(N) — 0.125 bytes/dim (97% savings)


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
    # tenant_id index is declared explicitly in __table_args__ below as
    # ix_data_sources_tenant; column-level `index=True` would add a
    # duplicate auto-named index.
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
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
        ForeignKey("tenant_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    connector_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cloud_file_id: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # The user who created this DataSource — used as ``actor_user_id`` when
    # the Celery extraction task invokes connector tools, so per-user
    # TenantConnection resolution (confused-deputy protection) still applies
    # outside the request thread. Nullable so system-created sources
    # (migrations, background seeds) don't need a synthetic user row.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Extraction results
    extraction_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    # Relationships
    chunks: Mapped[list[DataSourceChunk]] = relationship(back_populates="data_source", cascade="all, delete-orphan")
    # Application plugins may extend this model with back-populating
    # relationships (see docs/PLUGINS.md, "Extending core models").

    __table_args__ = (
        Index("ix_data_sources_tenant", "tenant_id"),
        Index("ix_data_sources_tenant_status", "tenant_id", "status"),
        Index("ix_data_sources_tenant_type", "tenant_id", "source_type"),
        # Added by 0030_datasource_actor_user — kept here so alembic
        # check sees the same name as the migration creates.
        Index("ix_data_sources_created_by_user", "created_by_user_id"),
    )


# ── Data Source Chunk ────────────────────────────────────


class VectorType(UserDefinedType):
    """SQLAlchemy type for pgvector's vector column.

    Handles serialization/deserialization between Python lists and
    PostgreSQL vector types. The precision parameter determines the
    underlying SQL type (vector, halfvec, or bit).
    """

    cache_ok = True

    def __init__(
        self,
        dimensions: int = 1536,
        precision: VectorPrecision | str = VectorPrecision.FULL,
    ):
        self.dimensions = dimensions
        self.precision = VectorPrecision(precision)

    def __eq__(self, other):
        return (
            isinstance(other, VectorType) and self.dimensions == other.dimensions and self.precision == other.precision
        )

    def __hash__(self):
        return hash((VectorType, self.dimensions, self.precision))

    def get_col_spec(self) -> str:
        if self.precision == VectorPrecision.HALF:
            return f"halfvec({self.dimensions})"
        if self.precision == VectorPrecision.BINARY:
            return f"bit({self.dimensions})"
        return f"vector({self.dimensions})"

    def bind_expression(self, bindvalue):
        return bindvalue

    def result_processor(self, dialect, coltype):
        """Parse pgvector string format '[1.0,2.0,3.0]' to Python list.

        Always returns list[float] or None — never leaks raw driver strings.
        """

        def process(value):
            if value is None:
                return None
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                stripped = value.strip("[]")
                if not stripped:
                    return []
                return [float(x) for x in stripped.split(",") if x.strip()]
            return None

        return process


class DataSourceChunk(TimestampMixin, Base):
    """A chunk of extracted content from a data source, with optional embedding."""

    __tablename__ = "data_source_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Indexes on tenant_id / data_source_id / parent_chunk_id are
    # declared in __table_args__ below with the names used by the
    # 0001 baseline migration (ix_dsc_part_tenant, ...); avoid
    # column-level `index=True` which would create duplicate index
    # declarations under SQLAlchemy's auto-generated names.
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Legacy JSONB embedding column — kept for backward compatibility during transition.
    # New code should use embedding_vec (native pgvector column) for storage and search.
    embedding: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    table_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Native pgvector column for hardware-accelerated similarity search (HNSW indexed).
    # Full-precision float32: 6,144 bytes per 1536-dim vector.
    embedding_vec: Mapped[list | None] = mapped_column(VectorType(1536), nullable=True)
    # Half-precision float16 column: 3,072 bytes per 1536-dim vector (50% savings).
    # Used as the primary search column when VECTOR_QUANTIZATION="half" is enabled.
    # The full-precision column is kept for accuracy-sensitive operations.
    embedding_halfvec: Mapped[list | None] = mapped_column(
        VectorType(1536, precision="half"),
        nullable=True,
    )
    # Auto-maintained tsvector for full-text search (GIN indexed via
    # ix_dsc_part_content_tsv, trigger-updated). Uses postgresql.TSVECTOR
    # so alembic autogenerate matches the actual DB column type.
    content_tsv: Mapped[str | None] = mapped_column("content_tsv", TSVECTOR, nullable=True)
    # Metadata for filtering
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=False, server_default="[]")
    content_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Contextual retrieval — document-level context prepended to chunk before embedding
    context_preamble: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_with_context: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Parent-child retrieval — small child chunks for matching, parent
    # chunks for context. Index lives in __table_args__ as a partial
    # (ix_dsc_parent_chunk WHERE parent_chunk_id IS NOT NULL).
    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    chunk_level: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        server_default="standard",
    )

    # Versioning — content_hash for incremental re-indexing, deleted_at for soft-delete
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    data_source: Mapped[DataSource] = relationship(back_populates="chunks")

    # Index declarations mirror the DDL in 0001_basic_schema's
    # _create_partitioned_chunks(). PostgreSQL propagates parent-table
    # indexes to all hash partitions automatically; the per-partition
    # HNSW indexes on the vector columns are excluded from autogenerate
    # via the env.py include_object filter.
    __table_args__ = (
        Index("ix_dsc_part_tenant", "tenant_id"),
        Index("ix_dsc_part_tenant_source", "tenant_id", "data_source_id"),
        Index("ix_dsc_part_tenant_type", "tenant_id", "content_type"),
        Index("ix_dsc_part_tenant_indexed", "tenant_id", "indexed_at"),
        Index("ix_dsc_part_content_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_dsc_parent_chunk",
            "parent_chunk_id",
            postgresql_where="parent_chunk_id IS NOT NULL",
        ),
        Index("ix_dsc_chunk_level", "tenant_id", "chunk_level"),
        Index(
            "ix_dsc_deleted_at",
            "deleted_at",
            postgresql_where="deleted_at IS NOT NULL",
        ),
        Index("ix_dsc_source_content_hash", "data_source_id", "content_hash"),
    )
