"""Enterprise SSO configuration models."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SSOProvider(enum.StrEnum):
    SAML = "saml"
    OIDC = "oidc"


class SSOConfiguration(TimestampMixin, Base):
    __tablename__ = "sso_configurations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, unique=True)
    provider_type: Mapped[SSOProvider] = mapped_column(Enum(SSOProvider), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    certificate: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    issuer_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    jit_provisioning: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
