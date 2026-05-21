"""Feature flag models."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class FeatureFlag(TimestampMixin, Base):
    __tablename__ = "feature_flags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rollout_percentage: Mapped[int] = mapped_column(Integer, default=0)

    overrides: Mapped[list[TenantFeatureOverride]] = relationship(back_populates="flag", cascade="all, delete-orphan")


class TenantFeatureOverride(TimestampMixin, Base):
    __tablename__ = "tenant_feature_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    flag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feature_flags.id"), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)

    flag: Mapped[FeatureFlag] = relationship(back_populates="overrides")

    __table_args__ = (UniqueConstraint("tenant_id", "flag_id", name="uq_tenant_flag"),)
