"""AI infrastructure models: provider keys, token wallet, usage logging, prompt templates."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

import structlog
from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, VersionMixin

logger = structlog.stdlib.get_logger()


# ── Provider Keys (BYOK) ─────────────────────────────────


class AIProvider(enum.StrEnum):
    """Supported AI providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    MISTRAL = "mistral"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"
    ALEPH_ALPHA = "aleph_alpha"


class TenantAIProviderKey(TimestampMixin, Base):
    """Encrypted BYOK API key for an AI provider, scoped to a tenant."""

    __tablename__ = "tenant_ai_provider_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    provider: Mapped[AIProvider] = mapped_column(Enum(AIProvider), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="default")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "display_name", name="uq_tenant_provider_key_name"),
        Index("ix_tenant_ai_keys_tenant_provider", "tenant_id", "provider"),
    )

    def set_api_key(self, plaintext: str) -> None:
        """Encrypt and store the AI provider API key."""
        from app.core.encryption import encrypt

        self.encrypted_api_key = encrypt(plaintext)

    def get_api_key(self) -> str | None:
        """Decrypt and return the AI provider API key."""
        if not self.encrypted_api_key:
            return None
        from app.core.encryption import decrypt

        try:
            return decrypt(self.encrypted_api_key)
        except Exception:
            logger.warning(
                "ai_provider_key_decrypt_failed",
                tenant_id=str(self.tenant_id),
                provider=self.provider,
            )
            return None


# ── Token Wallet ──────────────────────────────────────────


class TokenWallet(TimestampMixin, VersionMixin, Base):
    """Prepaid token balance per tenant. Uses optimistic locking via VersionMixin."""

    __tablename__ = "token_wallets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, unique=True)
    balance_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    lifetime_purchased: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    lifetime_consumed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class WalletTransactionType(enum.StrEnum):
    TOPUP = "topup"
    CONSUMPTION = "consumption"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"
    BONUS = "bonus"


class WalletTransaction(Base):
    """Immutable ledger entry for every wallet balance change."""

    __tablename__ = "wallet_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    type: Mapped[WalletTransactionType] = mapped_column(Enum(WalletTransactionType), nullable=False)
    amount_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        Index("ix_wallet_tx_tenant_created", "tenant_id", "created_at"),
    )


# ── AI Usage Logging ──────────────────────────────────────


class AIUsageLog(Base):
    """Per-request AI usage tracking for billing, analytics, and audit."""

    __tablename__ = "ai_usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8), default=0)
    billed_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="success")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_source: Mapped[str] = mapped_column(String(20), default="platform")
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        Index("ix_ai_usage_tenant_created", "tenant_id", "created_at"),
        Index("ix_ai_usage_tenant_model", "tenant_id", "model"),
    )


# ── Prompt Templates ──────────────────────────────────────


class PromptTemplate(SoftDeleteMixin, TimestampMixin, Base):
    """Reusable system prompt templates scoped to a tenant."""

    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_prompt_name"),
    )
