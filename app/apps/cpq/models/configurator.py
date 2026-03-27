"""Configuration session, selection, template, resolved BOM, and pricing models."""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, VersionMixin


# ── Enums ────────────────────────────────────────────────


class ConfigurationStatus(enum.StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    INVALID = "invalid"
    LOCKED = "locked"


class PricingRuleType(enum.StrEnum):
    BASE_PRICE = "base_price"
    OPTION_SURCHARGE = "option_surcharge"
    VOLUME_DISCOUNT = "volume_discount"
    CONDITIONAL = "conditional"
    FORMULA = "formula"
    TIERED = "tiered"
    MARGIN = "margin"


# ── Configuration Session ────────────────────────────────


class ConfigurationSession(AuditMixin, VersionMixin, TimestampMixin, Base):
    """An active or completed configuration being built by a user."""

    __tablename__ = "configuration_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    product_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_versions.id"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ConfigurationStatus] = mapped_column(
        Enum(ConfigurationStatus, values_callable=lambda e: [m.value for m in e], create_type=False),
        default=ConfigurationStatus.IN_PROGRESS,
    )

    is_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_errors: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Cached domain state after constraint propagation
    available_domains: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("configuration_templates.id"), nullable=True
    )
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    selections: Mapped[list[ConfigurationSelection]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    resolved_bom: Mapped[ConfiguredBOM | None] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    pricing: Mapped[ConfigurationPricing | None] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_config_sessions_tenant_product", "tenant_id", "product_id"),
        Index("ix_config_sessions_user", "user_id"),
        Index("ix_config_sessions_status", "tenant_id", "status"),
    )


class ConfigurationSelection(TimestampMixin, Base):
    """A single characteristic value selection within a configuration session."""

    __tablename__ = "configuration_selections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("configuration_sessions.id"), nullable=False, index=True
    )
    characteristic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("characteristics.id"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    is_auto_set: Mapped[bool] = mapped_column(Boolean, default=False)
    set_by_rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    session: Mapped[ConfigurationSession] = relationship(back_populates="selections")
    characteristic: Mapped["Characteristic"] = relationship()  # noqa: F821

    __table_args__ = (
        Index("ix_config_selections_session", "session_id"),
        Index("ix_config_selections_session_char", "session_id", "characteristic_id"),
    )


# ── Templates ────────────────────────────────────────────


class ConfigurationTemplate(AuditMixin, TimestampMixin, Base):
    """A saved partial or complete configuration for reuse."""

    __tablename__ = "configuration_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_partial: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    selections: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (
        Index("ix_config_templates_tenant_product", "tenant_id", "product_id"),
    )


# ── Resolved BOM ─────────────────────────────────────────


class ConfiguredBOM(AuditMixin, TimestampMixin, Base):
    """The resolved 100% BOM resulting from a completed configuration."""

    __tablename__ = "configured_boms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("configuration_sessions.id"), nullable=False, unique=True
    )
    bom_header_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bom_headers.id"), nullable=False, index=True
    )

    resolved_items: Mapped[list] = mapped_column(JSONB, nullable=False)
    total_components: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)

    selection_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    resolution_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped[ConfigurationSession] = relationship(back_populates="resolved_bom")

    __table_args__ = (
        Index("ix_configured_boms_tenant", "tenant_id"),
        Index("ix_configured_boms_session", "session_id"),
    )


# ── Pricing ──────────────────────────────────────────────


class PricingRule(SoftDeleteMixin, VersionMixin, TimestampMixin, Base):
    """A pricing rule for product configuration profitability analysis.

    Expression examples:
        BASE_PRICE: {"type": "base_price", "amount": 25000.00}
        OPTION_SURCHARGE: {"type": "option_surcharge",
            "condition": {"char": "engine", "op": "eq", "value": "V8"},
            "amount": 8500.00}
        MARGIN: {"type": "margin", "target_margin_pct": 35.0, "min_margin_pct": 20.0}
    """

    __tablename__ = "pricing_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_type: Mapped[PricingRuleType] = mapped_column(
        Enum(PricingRuleType, values_callable=lambda e: [m.value for m in e], create_type=False),
        nullable=False,
    )
    expression: Mapped[dict] = mapped_column(JSONB, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")

    __table_args__ = (
        Index("ix_pricing_rules_product", "product_id"),
        Index("ix_pricing_rules_product_type", "product_id", "rule_type"),
    )


class ConfigurationPricing(AuditMixin, TimestampMixin, Base):
    """Resolved pricing and profitability for a configuration session."""

    __tablename__ = "configuration_pricing"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("configuration_sessions.id"), nullable=False, unique=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    base_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    total_adjustments: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    final_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    margin_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    margin_percentage: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    price_breakdown: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_profitable: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    session: Mapped[ConfigurationSession] = relationship(back_populates="pricing")

    __table_args__ = (
        Index("ix_config_pricing_tenant", "tenant_id"),
        Index("ix_config_pricing_session", "session_id"),
    )
