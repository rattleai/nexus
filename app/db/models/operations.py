"""Job processing, audit logging, and GDPR compliance models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, VersionMixin
from app.db.models.mobile import SyncMixin

if TYPE_CHECKING:
    from app.db.models.core import Tenant


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(SyncMixin, SoftDeleteMixin, VersionMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, values_callable=lambda e: [m.value for m in e]), default=JobStatus.PENDING, index=True
    )
    input_hash: Mapped[str | None] = mapped_column(String(64))
    webhook_url: Mapped[str | None] = mapped_column(String(2048))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)

    tenant: Mapped[Tenant] = relationship(back_populates="jobs")

    __table_args__ = (Index("ix_jobs_tenant_status", "tenant_id", "status"),)


class AuditLog(Base):
    """Immutable, append-only audit trail for compliance (SOC2, GDPR)."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(50), default="user")
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_audit_logs_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_audit_logs_actor_occurred", "actor_id", "occurred_at"),
    )


# ── GDPR Compliance ──────────────────────────────────────────────────────


class ConsentType(enum.StrEnum):
    TERMS_OF_SERVICE = "terms_of_service"
    PRIVACY_POLICY = "privacy_policy"
    MARKETING = "marketing"
    DATA_PROCESSING = "data_processing"
    COOKIES = "cookies"
    THIRD_PARTY_SHARING = "third_party_sharing"


class Consent(TimestampMixin, Base):
    """Tracks user consent for GDPR compliance.

    Records when and how consent was given or withdrawn, with version
    tracking for policy documents.
    """

    __tablename__ = "consents"
    __table_args__ = (
        Index("ix_consents_user_type", "user_id", "consent_type"),
        Index("ix_consents_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    consent_type: Mapped[ConsentType] = mapped_column(
        Enum(ConsentType, name="consent_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DSARStatus(enum.StrEnum):
    """Data Subject Access Request status."""

    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"


class DSARType(enum.StrEnum):
    """Types of Data Subject Access Requests."""

    ACCESS = "access"  # Right to access (Art. 15)
    RECTIFICATION = "rectification"  # Right to rectification (Art. 16)
    ERASURE = "erasure"  # Right to erasure (Art. 17)
    PORTABILITY = "portability"  # Right to data portability (Art. 20)
    RESTRICTION = "restriction"  # Right to restriction (Art. 18)
    OBJECTION = "objection"  # Right to object (Art. 21)


class DataSubjectRequest(TimestampMixin, Base):
    """Tracks GDPR Data Subject Access Requests (DSARs).

    Ensures compliance with GDPR Articles 15-21, tracking request
    status, SLA adherence, and completion evidence.
    """

    __tablename__ = "data_subject_requests"
    __table_args__ = (
        Index("ix_dsar_tenant_status", "tenant_id", "status"),
        Index("ix_dsar_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    request_type: Mapped[DSARType] = mapped_column(
        Enum(DSARType, name="dsar_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    status: Mapped[DSARStatus] = mapped_column(
        Enum(DSARStatus, name="dsar_status", values_callable=lambda e: [m.value for m in e]),
        default=DSARStatus.RECEIVED,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SLA tracking: GDPR requires response within 30 days
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Evidence of completion (e.g., export file reference)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    processed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class DataRetentionPolicy(TimestampMixin, VersionMixin, Base):
    """Configurable data retention policies per tenant per resource type.

    Defines how long different types of data should be kept before
    automatic purging.
    """

    __tablename__ = "data_retention_policies"
    __table_args__ = (Index("ix_retention_tenant_resource", "tenant_id", "resource_type", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)

    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    archive_before_delete: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
