"""Database models for mobile-first features.

Includes push notification subscriptions, WebAuthn credentials,
and offline sync change log.
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin


class PushSubscription(Base, TimestampMixin):
    """Push notification subscription for Web Push, FCM, or APNs."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(10), nullable=False)  # web, fcm, apns
    subscription_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_push_subscriptions_user", "user_id", "active"),
        Index("ix_push_subscriptions_tenant", "tenant_id"),
    )


class WebAuthnCredential(Base, TimestampMixin):
    """WebAuthn/FIDO2 credential for biometric authentication."""

    __tablename__ = "webauthn_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    credential_id: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_used_at: Mapped[None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_webauthn_user", "user_id"),
        Index("ix_webauthn_credential_id", "credential_id", unique=True),
    )


class ChangeLog(Base, TimestampMixin):
    """Change log for offline-first data synchronization.

    Records all create/update/delete operations for syncable entities.
    Mobile clients pull changes since their last sync_version.
    """

    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "job", "notification"
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(10), nullable=False)  # create, update, delete
    changed_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sync_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))

    __table_args__ = (
        Index("ix_changelog_tenant_entity_version", "tenant_id", "entity_type", "sync_version"),
        Index("ix_changelog_entity", "entity_type", "entity_id"),
    )


class SyncMixin:
    """Mixin for models that support offline synchronization.

    Add to any model that mobile clients need to sync offline.
    """

    sync_version: Mapped[int] = mapped_column(BigInteger, server_default=text("0"), nullable=False)
    sync_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
