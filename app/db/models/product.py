"""Product catalog, characteristics, constraint rules, variant tables, and media models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, VersionMixin


# ── Enums ────────────────────────────────────────────────


class ProductStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class CharacteristicType(enum.StrEnum):
    ENUM = "enum"
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    TEXT = "text"


class ConstraintType(enum.StrEnum):
    REQUIRES = "requires"
    EXCLUDES = "excludes"
    SELECTION_CONDITION = "selection_condition"
    DEFAULT_VALUE = "default_value"
    FORMULA = "formula"
    TABLE = "table"


# ── Product Catalog ──────────────────────────────────────


class ProductFamily(SoftDeleteMixin, AuditMixin, VersionMixin, TimestampMixin, Base):
    """Top-level grouping of related configurable products."""

    __tablename__ = "product_families"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    products: Mapped[list[Product]] = relationship(back_populates="family", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_product_family_slug"),
        Index("ix_product_families_tenant", "tenant_id"),
    )


class Product(SoftDeleteMixin, AuditMixin, VersionMixin, TimestampMixin, Base):
    """A configurable product definition."""

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    family_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product_families.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku_prefix: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus, values_callable=lambda e: [m.value for m in e]),
        default=ProductStatus.DRAFT,
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    family: Mapped[ProductFamily | None] = relationship(back_populates="products")
    versions: Mapped[list[ProductVersion]] = relationship(back_populates="product", cascade="all, delete-orphan")
    characteristic_assignments: Mapped[list[CharacteristicAssignment]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    constraint_rules: Mapped[list[ConstraintRule]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    constraint_groups: Mapped[list[ConstraintGroup]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    variant_tables: Mapped[list[VariantTable]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    # Cross-module relationships (lazy string references)
    bom_headers: Mapped[list["BOMHeader"]] = relationship(  # noqa: F821
        back_populates="product", cascade="all, delete-orphan",
        foreign_keys="[BOMHeader.product_id]",
    )
    pricing_rules: Mapped[list["PricingRule"]] = relationship(  # noqa: F821
        cascade="all, delete-orphan",
        foreign_keys="[PricingRule.product_id]",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_product_slug"),
        Index("ix_products_tenant_status", "tenant_id", "status"),
    )


class ProductVersion(AuditMixin, TimestampMixin, Base):
    """Immutable snapshot of a product configuration model at a point in time."""

    __tablename__ = "product_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[Product] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("product_id", "version_number", name="uq_product_version_number"),
        Index("ix_product_versions_product_active", "product_id", "is_active"),
    )


# ── Characteristic / Option Layer ────────────────────────


class CharacteristicGroup(SoftDeleteMixin, TimestampMixin, Base):
    """Groups related characteristics (e.g. "Engine Options", "Exterior Colors")."""

    __tablename__ = "characteristic_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    characteristics: Mapped[list[Characteristic]] = relationship(back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_char_group_slug"),
    )


class Characteristic(SoftDeleteMixin, VersionMixin, TimestampMixin, Base):
    """An individual configurable option/feature (SAP "characteristic")."""

    __tablename__ = "characteristics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("characteristic_groups.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_type: Mapped[CharacteristicType] = mapped_column(
        Enum(CharacteristicType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    numeric_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    numeric_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    numeric_step: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_multi_select: Mapped[bool] = mapped_column(Boolean, default=False)
    default_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    group: Mapped[CharacteristicGroup | None] = relationship(back_populates="characteristics")
    values: Mapped[list[CharacteristicValue]] = relationship(
        back_populates="characteristic",
        cascade="all, delete-orphan",
        order_by="CharacteristicValue.display_order",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_characteristic_slug"),
        Index("ix_characteristics_tenant_group", "tenant_id", "group_id"),
    )


class CharacteristicValue(TimestampMixin, Base):
    """An allowed value for an enum-type characteristic."""

    __tablename__ = "characteristic_values"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    characteristic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("characteristics.id"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    price_adjustment: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    characteristic: Mapped[Characteristic] = relationship(back_populates="values")

    __table_args__ = (
        UniqueConstraint("characteristic_id", "value", name="uq_char_value"),
        Index("ix_char_values_characteristic", "characteristic_id"),
    )


class CharacteristicAssignment(TimestampMixin, Base):
    """Links a characteristic to a product, with product-specific overrides."""

    __tablename__ = "characteristic_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    characteristic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("characteristics.id"), nullable=False, index=True
    )
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    default_value: Mapped[str | None] = mapped_column(String(500), nullable=True)

    product: Mapped[Product] = relationship(back_populates="characteristic_assignments")
    characteristic: Mapped[Characteristic] = relationship()

    __table_args__ = (
        UniqueConstraint("product_id", "characteristic_id", name="uq_product_characteristic"),
        Index("ix_char_assignments_product", "product_id"),
    )


# ── Constraint / Rule Engine Layer ───────────────────────


class ConstraintGroup(SoftDeleteMixin, TimestampMixin, Base):
    """A dependency net — groups related constraints for organization."""

    __tablename__ = "constraint_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[Product] = relationship(back_populates="constraint_groups")
    rules: Mapped[list[ConstraintRule]] = relationship(back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_constraint_groups_product", "product_id"),
    )


class ConstraintRule(SoftDeleteMixin, VersionMixin, TimestampMixin, Base):
    """A single configuration constraint/rule with JSONB AST expression.

    Expression examples:
        REQUIRES: {"type": "requires",
                    "if": {"char": "engine", "op": "eq", "value": "V8"},
                    "then": {"char": "transmission", "op": "in", "value": ["auto_6", "auto_8"]}}
        EXCLUDES: {"type": "excludes",
                    "if": {"char": "trim", "op": "eq", "value": "base"},
                    "then": {"char": "sunroof", "op": "eq", "value": "panoramic"}}
    """

    __tablename__ = "constraint_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("constraint_groups.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraint_type: Mapped[ConstraintType] = mapped_column(
        Enum(ConstraintType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    expression: Mapped[dict] = mapped_column(JSONB, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[Product] = relationship(back_populates="constraint_rules")
    group: Mapped[ConstraintGroup | None] = relationship(back_populates="rules")

    __table_args__ = (
        Index("ix_constraint_rules_product", "product_id"),
        Index("ix_constraint_rules_product_type", "product_id", "constraint_type"),
    )


class VariantTable(TimestampMixin, Base):
    """Tabular constraint data for table-based lookups."""

    __tablename__ = "variant_tables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    columns: Mapped[list] = mapped_column(JSONB, nullable=False)
    rows: Mapped[list] = mapped_column(JSONB, nullable=False)
    input_columns: Mapped[list] = mapped_column(JSONB, nullable=False)
    output_columns: Mapped[list] = mapped_column(JSONB, nullable=False)

    product: Mapped[Product] = relationship(back_populates="variant_tables")

    __table_args__ = (
        Index("ix_variant_tables_product", "product_id"),
    )


# ── Media / Asset Layer ──────────────────────────────────


class ProductMedia(TimestampMixin, Base):
    """Media assets linked to products, characteristics, or values."""

    __tablename__ = "product_media"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    media_type: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    alt_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (
        Index("ix_product_media_entity", "entity_type", "entity_id"),
        Index("ix_product_media_tenant", "tenant_id"),
    )
