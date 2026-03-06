"""AI-specific domain events."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.events import DomainEvent


@dataclass
class AICompletionRequested(DomainEvent):
    tenant_id: str = ""
    model: str = ""
    request_id: str = ""
    stream: bool = False


@dataclass
class AICompletionCompleted(DomainEvent):
    tenant_id: str = ""
    model: str = ""
    provider: str = ""
    total_tokens: int = 0
    billed_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    key_source: str = ""
    request_id: str = ""


@dataclass
class AICompletionFailed(DomainEvent):
    tenant_id: str = ""
    model: str = ""
    provider: str = ""
    error: str = ""
    request_id: str = ""


@dataclass
class WalletTopupCompleted(DomainEvent):
    tenant_id: str = ""
    amount_tokens: int = 0
    new_balance: int = 0
    reference_id: str = ""


@dataclass
class WalletBalanceLow(DomainEvent):
    tenant_id: str = ""
    balance_tokens: int = 0
    threshold: int = 0


@dataclass
class AIProviderKeyCreated(DomainEvent):
    tenant_id: str = ""
    provider: str = ""
    key_id: str = ""


@dataclass
class AIProviderKeyDeleted(DomainEvent):
    tenant_id: str = ""
    provider: str = ""
    key_id: str = ""
