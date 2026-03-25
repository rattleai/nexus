"""Bill of Materials models — 150% super BOM and configured BOM support."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, VersionMixin


class BOMItemType(enum.StrEnum):
    COMPONENT = "component"
    SUB_ASSEMBLY = "sub_assembly"
    PHANTOM = "phantom"
    REFERENCE = "reference"


class BOMHeader(SoftDeleteMixin, AuditMixin, VersionMixin, TimestampMixin, Base):
    """Top-level BOM definition — the 150% super BOM.

    Each product can have multiple BOM alternatives. One is marked as primary.
    """

    __tablename__ = "bom_headers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    bom_type: Mapped[str] = mapped_column(String(50), default="manufacturing")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    items: Mapped[list[BOMItem]] = relationship(
        back_populates="bom_header",
        cascade="all, delete-orphan",
        order_by="BOMItem.sort_order",
    )

    __table_args__ = (
        Index("ix_bom_headers_product", "product_id"),
        Index("ix_bom_headers_tenant_product", "tenant_id", "product_id"),
    )


class BOMItem(SoftDeleteMixin, VersionMixin, TimestampMixin, Base):
    """A single item in a 150% BOM (super BOM).

    Each item has an optional selection_condition (JSONB AST) that determines
    whether it is included in the configured 100% BOM based on the user's
    characteristic selections.

    For multi-level BOMs, sub_product_id references another configurable product.
    """

    __tablename__ = "bom_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    bom_header_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bom_headers.id"), nullable=False, index=True)
    parent_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bom_items.id"), nullable=True, index=True
    )

    item_type: Mapped[BOMItemType] = mapped_column(
        Enum(BOMItemType, values_callable=lambda e: [m.value for m in e]),
        default=BOMItemType.COMPONENT,
    )
    part_number: Mapped[str] = mapped_column(String(100), nullable=False)
    part_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("1.0000"))
    quantity_expression: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    unit_of_measure: Mapped[str] = mapped_column(String(20), default="EA")

    sub_product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id"), nullable=True, index=True
    )

    # JSONB AST evaluated against configuration selections; null = always included
    selection_condition: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    bom_header: Mapped[BOMHeader] = relationship(back_populates="items")
    parent_item: Mapped[BOMItem | None] = relationship(remote_side="BOMItem.id", back_populates="children")
    children: Mapped[list[BOMItem]] = relationship(back_populates="parent_item", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_bom_items_header", "bom_header_id"),
        Index("ix_bom_items_part_number", "tenant_id", "part_number"),
    )
