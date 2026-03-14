# Multi-Provider AI Integration Infrastructure — Implementation Plan

## Executive Summary

Production-grade, multi-provider AI/LLM gateway for the existing multitenant SaaS platform. Uses **LiteLLM** as the unified provider abstraction layer, supporting OpenAI, Anthropic, Google Gemini, Mistral, DeepSeek, Qwen, and Aleph Alpha through a single normalized interface. Features a **prepaid token wallet** billing model with platform margin, **BYOK + platform-managed keys**, SSE streaming, circuit breaker failover, and full observability.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                        API Layer                             │
│  POST /api/v1/ai/completions          (sync + streaming)    │
│  POST /api/v1/ai/completions/async    (Celery-backed)       │
│  GET  /api/v1/ai/models               (available models)    │
│  CRUD /api/v1/ai/provider-keys        (tenant BYOK mgmt)   │
│  CRUD /api/v1/ai/prompt-templates     (tenant templates)    │
│  GET  /api/v1/ai/usage                (token usage stats)   │
│  POST /api/v1/ai/wallet/topup         (prepaid wallet)      │
│  GET  /api/v1/ai/wallet/balance       (wallet balance)      │
│  GET  /api/v1/ai/wallet/transactions  (wallet history)      │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│                     AI Service Layer                         │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────────────────┐ │
│  │  Guardrails │ │ Wallet Check │ │ Key Resolution        │ │
│  │  (input     │ │ (prepaid     │ │ (BYOK → platform key  │ │
│  │   validation│ │  balance     │ │  fallback)            │ │
│  │   + output  │ │  deduction)  │ │                       │ │
│  │   filtering)│ │              │ │                       │ │
│  └──────┬──────┘ └──────┬───────┘ └───────────┬───────────┘ │
│         │               │                     │             │
│  ┌──────▼───────────────▼─────────────────────▼───────────┐ │
│  │              AI Gateway (LiteLLM)                      │ │
│  │  ┌─────────────┐ ┌──────────────┐ ┌─────────────────┐ │ │
│  │  │ Circuit     │ │ Retry w/     │ │ Model Fallback  │ │ │
│  │  │ Breaker     │ │ Exp. Backoff │ │ Chains          │ │ │
│  │  └─────────────┘ └──────────────┘ └─────────────────┘ │ │
│  └────────────────────────┬───────────────────────────────┘ │
│                           │                                 │
│  ┌────────────────────────▼───────────────────────────────┐ │
│  │           Observability & Metering                     │ │
│  │  • Prometheus metrics  • Structured logging            │ │
│  │  • OTel spans          • Domain events                 │ │
│  │  • Token counting      • Cost calculation              │ │
│  │  • Audit logging       • Usage records (DB)            │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                │
    ┌───────────┼───────────┬───────────┬──────────┐
    ▼           ▼           ▼           ▼          ▼
 OpenAI    Anthropic    Gemini    Mistral    DeepSeek ...
```

---

## File Structure

```
app/ai/
├── __init__.py                 # Package init, re-exports
├── gateway.py                  # Core LiteLLM gateway wrapper
├── providers.py                # Provider registry & model catalog
├── schemas.py                  # Pydantic request/response schemas
├── wallet.py                   # Prepaid token wallet (Redis + DB)
├── guardrails.py               # Input validation & output filtering
├── key_resolver.py             # BYOK + platform key resolution
├── streaming.py                # SSE streaming helper
├── cost.py                     # Token counting & cost calculation with margin
├── events.py                   # AI-specific domain events
├── metrics.py                  # Prometheus counters/histograms for AI
├── tasks.py                    # Celery tasks for async AI calls
└── dependencies.py             # FastAPI dependencies (wallet check, etc.)

app/api/v1/ai.py                # API route handlers
app/db/migrations/versions/a005_ai_infrastructure.py  # DB migration
```

---

## 1. Database Models (in `app/db/models.py`)

### 1.1 TenantAIProviderKey — BYOK encrypted key storage
```python
class TenantAIProviderKey(TimestampMixin, Base):
    __tablename__ = "tenant_ai_provider_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)          # "openai", "anthropic", etc.
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)       # Fernet-encrypted
    display_name: Mapped[str] = mapped_column(String(255), default="default")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Encrypt/decrypt helpers following OAuthAccount pattern
    def set_api_key(self, plaintext: str) -> None: ...
    def get_api_key(self) -> str | None: ...

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "display_name", name="uq_tenant_provider_key_name"),
        Index("ix_tenant_ai_keys_tenant_provider", "tenant_id", "provider"),
    )
```

### 1.2 TokenWallet — Prepaid balance per tenant
```python
class TokenWallet(TimestampMixin, VersionMixin, Base):
    __tablename__ = "token_wallets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, unique=True)
    balance_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)  # current token balance
    lifetime_purchased: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    lifetime_consumed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
```

### 1.3 WalletTransaction — Immutable ledger for all wallet changes
```python
class WalletTransactionType(enum.StrEnum):
    TOPUP = "topup"         # Purchase/credit
    CONSUMPTION = "consumption"  # AI usage deduction
    REFUND = "refund"       # Error refund
    ADJUSTMENT = "adjustment"   # Admin adjustment
    BONUS = "bonus"         # Promotional credit

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    type: Mapped[WalletTransactionType] = mapped_column(Enum(WalletTransactionType), nullable=False)
    amount_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)  # positive for credit, negative for debit
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)  # snapshot after this transaction
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # e.g. stripe_payment_id, ai_usage_log_id
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        Index("ix_wallet_tx_tenant_created", "tenant_id", "created_at"),
    )
```

### 1.4 AIUsageLog — Per-request AI usage tracking
```python
class AIUsageLog(Base):
    __tablename__ = "ai_usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 8), default=0)         # raw provider cost
    billed_tokens: Mapped[int] = mapped_column(Integer, default=0)              # tokens charged (with margin)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="success")          # success, error, timeout
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_source: Mapped[str] = mapped_column(String(20), default="platform")     # "byok" or "platform"
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        Index("ix_ai_usage_tenant_created", "tenant_id", "created_at"),
        Index("ix_ai_usage_tenant_model", "tenant_id", "model"),
    )
```

### 1.5 PromptTemplate — Reusable system prompt templates per tenant
```python
class PromptTemplate(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # ["user_name", "company"]
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_prompt_name"),
    )
```

---

## 2. Provider Registry & Model Catalog (`app/ai/providers.py`)

```python
# Enum of supported providers
class AIProvider(enum.StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"           # Gemini via litellm "gemini/" prefix
    MISTRAL = "mistral"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"              # via litellm "openai/" with custom base_url or native
    ALEPH_ALPHA = "aleph_alpha"

# Model catalog with metadata
MODEL_CATALOG: dict[str, ModelInfo] = {
    "gpt-4o": ModelInfo(provider=AIProvider.OPENAI, litellm_model="gpt-4o", ...),
    "gpt-4o-mini": ModelInfo(provider=AIProvider.OPENAI, litellm_model="gpt-4o-mini", ...),
    "claude-sonnet-4-20250514": ModelInfo(provider=AIProvider.ANTHROPIC, litellm_model="claude-sonnet-4-20250514", ...),
    "claude-haiku-4-5-20251001": ModelInfo(provider=AIProvider.ANTHROPIC, litellm_model="claude-haiku-4-5-20251001", ...),
    "gemini-2.0-flash": ModelInfo(provider=AIProvider.GOOGLE, litellm_model="gemini/gemini-2.0-flash", ...),
    "mistral-large-latest": ModelInfo(provider=AIProvider.MISTRAL, litellm_model="mistral/mistral-large-latest", ...),
    "deepseek-chat": ModelInfo(provider=AIProvider.DEEPSEEK, litellm_model="deepseek/deepseek-chat", ...),
    "qwen-turbo": ModelInfo(provider=AIProvider.QWEN, litellm_model="openai/qwen-turbo", ...),
    # ... more models
}

# Platform-level env var mapping for platform-managed keys
PROVIDER_ENV_VARS: dict[AIProvider, str] = {
    AIProvider.OPENAI: "AI_OPENAI_API_KEY",
    AIProvider.ANTHROPIC: "AI_ANTHROPIC_API_KEY",
    AIProvider.GOOGLE: "AI_GOOGLE_API_KEY",
    AIProvider.MISTRAL: "AI_MISTRAL_API_KEY",
    AIProvider.DEEPSEEK: "AI_DEEPSEEK_API_KEY",
    AIProvider.QWEN: "AI_QWEN_API_KEY",
    AIProvider.ALEPH_ALPHA: "AI_ALEPH_ALPHA_API_KEY",
}

# Default fallback chains per provider (used when primary provider is down)
DEFAULT_FALLBACK_CHAINS: dict[str, list[str]] = {
    "gpt-4o": ["claude-sonnet-4-20250514", "gemini-2.0-flash"],
    "claude-sonnet-4-20250514": ["gpt-4o", "gemini-2.0-flash"],
    # ...
}
```

---

## 3. Key Resolver (`app/ai/key_resolver.py`)

Resolves the API key for a given provider+tenant:

1. Check tenant's BYOK keys in DB (encrypted, cached in Redis for 5min)
2. Fall back to platform-managed keys from environment variables
3. Raise error if neither available

```python
async def resolve_api_key(
    tenant_id: uuid.UUID,
    provider: AIProvider,
    db: AsyncSession,
) -> tuple[str, str]:
    """Returns (api_key, source) where source is 'byok' or 'platform'."""
```

Uses existing `app.core.encryption.decrypt()` and `app.core.cache.@cached()`.

---

## 4. Prepaid Token Wallet (`app/ai/wallet.py`)

### Design
- **Redis for hot balance** (fast reads/writes during AI calls) + **DB for persistence** (periodic sync, transactions ledger)
- **Atomic deduction** via Redis Lua script (check balance + deduct in one operation)
- **Margin calculation**: Platform applies configurable margin (e.g., 1.2x) to raw token count
- **Estimated pre-deduction**: Before AI call, estimate max tokens and reserve them. After call, adjust with actual usage and refund difference.

```python
# Redis Lua script for atomic balance check + deduction
DEDUCT_SCRIPT = """
local balance = tonumber(redis.call('GET', KEYS[1]) or '0')
local amount = tonumber(ARGV[1])
if balance < amount then
    return -1  -- insufficient
end
redis.call('DECRBY', KEYS[1], amount)
return balance - amount
"""

class TokenWalletService:
    MARGIN_MULTIPLIER = 1.15  # 15% platform margin (configurable via settings)

    async def get_balance(self, tenant_id: uuid.UUID) -> int: ...
    async def reserve_tokens(self, tenant_id: uuid.UUID, estimated_tokens: int) -> str:
        """Reserve tokens before AI call. Returns reservation_id."""
    async def settle_reservation(self, reservation_id: str, actual_tokens: int) -> None:
        """Settle after AI call: charge actual, refund difference."""
    async def topup(self, tenant_id: uuid.UUID, amount_tokens: int, reference_id: str, db: AsyncSession) -> int:
        """Credit tokens (after payment). Returns new balance."""
    async def _apply_margin(self, raw_tokens: int) -> int:
        """Apply platform margin to raw token count."""
    async def _sync_to_db(self, tenant_id: uuid.UUID, db: AsyncSession) -> None:
        """Periodic: sync Redis balance to DB for durability."""
```

---

## 5. AI Gateway (`app/ai/gateway.py`)

Core gateway wrapping LiteLLM with full infrastructure integration:

```python
class AIGateway:
    """Production-grade AI gateway with circuit breaker, retry, streaming, and observability."""

    def __init__(self):
        self.breaker = CircuitBreaker("ai", failure_threshold=5, recovery_timeout=120)

    async def completion(
        self,
        *,
        tenant_id: uuid.UUID,
        model: str,
        messages: list[dict],
        api_key: str,
        key_source: str,
        stream: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        fallback_models: list[str] | None = None,
        request_id: str | None = None,
        **kwargs,
    ) -> AICompletionResult | AsyncGenerator[AIStreamChunk, None]:
        """
        Flow:
        1. Check circuit breaker for provider
        2. Call litellm.acompletion() (or litellm.acompletion() with stream=True)
        3. On success: record_success on breaker, emit metrics, return result
        4. On failure: record_failure on breaker, try fallback models
        5. Track tokens, cost, latency in AIUsageLog
        """

    async def _call_litellm(self, model: str, api_key: str, messages: list, stream: bool, **kwargs):
        """Direct LiteLLM call with timeout and error handling."""
        import litellm
        return await litellm.acompletion(
            model=model_info.litellm_model,
            messages=messages,
            api_key=api_key,
            stream=stream,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=30,  # configurable
            **kwargs,
        )

    async def _try_with_fallbacks(self, models: list[str], ...):
        """Try primary model, then each fallback in order."""
```

---

## 6. SSE Streaming (`app/ai/streaming.py`)

```python
from fastapi.responses import StreamingResponse

async def stream_completion(
    gateway: AIGateway,
    request_params: dict,
) -> StreamingResponse:
    """Wrap LiteLLM streaming response as SSE for the client."""

    async def event_generator():
        total_tokens = 0
        async for chunk in gateway.completion(**request_params, stream=True):
            # Format as SSE: data: {...}\n\n
            yield f"data: {chunk.model_dump_json()}\n\n"
            total_tokens += chunk.tokens

        # Final usage event
        yield f"data: {json.dumps({'type': 'usage', 'total_tokens': total_tokens})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

---

## 7. Guardrails (`app/ai/guardrails.py`)

Basic input validation and output filtering:

```python
class AIGuardrails:
    # Configurable per tenant via tenant.settings["ai_guardrails"]

    async def validate_input(self, messages: list[dict], tenant_settings: dict) -> list[str]:
        """Returns list of violations (empty = OK). Checks:
        - Max input token count (prevents budget blowout)
        - Blocked keyword patterns (regex, configurable per tenant)
        - Max message count per request
        - Max individual message length
        """

    async def filter_output(self, content: str, tenant_settings: dict) -> str:
        """Post-process output. Filters:
        - PII pattern detection (email, phone, SSN) - optional per tenant
        - Configurable blocked output patterns
        Returns filtered content.
        """
```

---

## 8. Pydantic Schemas (`app/ai/schemas.py`)

```python
# ── Request ──
class AICompletionRequest(BaseModel):
    model: str = Field(..., description="Model ID from catalog")
    messages: list[AIMessage] = Field(..., min_length=1, max_length=100)
    max_tokens: int | None = Field(default=None, ge=1, le=128000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    stream: bool = Field(default=False)
    template_id: uuid.UUID | None = Field(default=None, description="Optional prompt template to prepend")
    fallback_models: list[str] | None = Field(default=None, max_length=3)

class AIMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1, max_length=200_000)

# ── Response ──
class AICompletionResponse(BaseModel):
    id: str
    model: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    billed_tokens: int      # tokens charged to wallet (with margin)
    cost_usd: float
    latency_ms: int
    key_source: str         # "byok" or "platform"
    finish_reason: str | None

# ── Streaming chunk ──
class AIStreamChunk(BaseModel):
    id: str
    delta: str              # incremental content
    finish_reason: str | None = None

# ── Wallet ──
class WalletBalanceResponse(BaseModel):
    balance_tokens: int
    lifetime_purchased: int
    lifetime_consumed: int

class WalletTopupRequest(BaseModel):
    amount_tokens: int = Field(..., ge=1000, le=100_000_000)
    payment_method: str = Field(default="stripe")

class WalletTransactionResponse(BaseModel):
    id: uuid.UUID
    type: str
    amount_tokens: int
    balance_after: int
    description: str | None
    created_at: datetime

# ── Provider Keys ──
class ProviderKeyCreate(BaseModel):
    provider: str = Field(..., pattern=r"^[a-z_]+$")
    api_key: str = Field(..., min_length=10, max_length=500)
    display_name: str = Field(default="default", max_length=255)

class ProviderKeyResponse(BaseModel):
    id: uuid.UUID
    provider: str
    display_name: str
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime
    # NOTE: api_key is NEVER returned

# ── Prompt Templates ──
class PromptTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    system_prompt: str = Field(..., min_length=1, max_length=50_000)
    description: str | None = None
    variables: list[str] | None = None

class PromptTemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    system_prompt: str
    variables: list[str] | None
    is_default: bool
    created_at: datetime

# ── Usage ──
class AIUsageResponse(BaseModel):
    total_requests: int
    total_tokens: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float
    by_model: list[ModelUsageSummary]
    period_start: datetime
    period_end: datetime

# ── Models ──
class ModelInfoResponse(BaseModel):
    model_id: str
    provider: str
    max_tokens: int
    supports_streaming: bool
    supports_function_calling: bool
    available: bool             # True if platform key or tenant BYOK exists
```

---

## 9. API Endpoints (`app/api/v1/ai.py`)

```python
router = APIRouter(prefix="/ai")

# ── Completions ──
@router.post("/completions", response_model=AICompletionResponse)
async def create_completion(
    request: AICompletionRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Synchronous AI completion. Supports streaming via stream=True (returns SSE)."""

@router.post("/completions/async", response_model=JobResponse)
async def create_async_completion(
    request: AICompletionRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Async AI completion via Celery. Returns a Job that can be polled."""

# ── Models ──
@router.get("/models", response_model=list[ModelInfoResponse])
async def list_models(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all available models (filtered by tenant's configured providers)."""

# ── Provider Keys (BYOK) ──
@router.post("/provider-keys", response_model=ProviderKeyResponse,
             dependencies=[Depends(RequireScopes("ai:admin"))])
async def create_provider_key(...): ...

@router.get("/provider-keys", response_model=list[ProviderKeyResponse],
            dependencies=[Depends(RequireScopes("ai:read"))])
async def list_provider_keys(...): ...

@router.delete("/provider-keys/{key_id}",
               dependencies=[Depends(RequireScopes("ai:admin"))])
async def delete_provider_key(...): ...

# ── Wallet ──
@router.get("/wallet/balance", response_model=WalletBalanceResponse,
            dependencies=[Depends(RequireScopes("ai:read"))])
async def get_wallet_balance(...): ...

@router.post("/wallet/topup",
             dependencies=[Depends(RequireScopes("ai:admin"))])
async def topup_wallet(...): ...

@router.get("/wallet/transactions",
            response_model=CursorPaginatedResponse[WalletTransactionResponse],
            dependencies=[Depends(RequireScopes("ai:read"))])
async def list_wallet_transactions(...): ...

# ── Prompt Templates ──
@router.post("/prompt-templates", response_model=PromptTemplateResponse,
             dependencies=[Depends(RequireScopes("ai:write"))])
async def create_prompt_template(...): ...

@router.get("/prompt-templates", response_model=list[PromptTemplateResponse],
            dependencies=[Depends(RequireScopes("ai:read"))])
async def list_prompt_templates(...): ...

@router.put("/prompt-templates/{template_id}",
            dependencies=[Depends(RequireScopes("ai:write"))])
async def update_prompt_template(...): ...

@router.delete("/prompt-templates/{template_id}",
               dependencies=[Depends(RequireScopes("ai:admin"))])
async def delete_prompt_template(...): ...

# ── Usage ──
@router.get("/usage", response_model=AIUsageResponse,
            dependencies=[Depends(RequireScopes("ai:read"))])
async def get_usage_stats(...): ...
```

---

## 10. Domain Events (`app/ai/events.py`)

```python
@dataclass
class AICompletionRequested(DomainEvent):
    tenant_id: str = ""
    model: str = ""
    request_id: str = ""

@dataclass
class AICompletionCompleted(DomainEvent):
    tenant_id: str = ""
    model: str = ""
    total_tokens: int = 0
    cost_usd: float = 0
    latency_ms: int = 0
    request_id: str = ""

@dataclass
class AICompletionFailed(DomainEvent):
    tenant_id: str = ""
    model: str = ""
    error: str = ""
    request_id: str = ""

@dataclass
class WalletTopupCompleted(DomainEvent):
    tenant_id: str = ""
    amount_tokens: int = 0
    new_balance: int = 0

@dataclass
class WalletBalanceLow(DomainEvent):
    tenant_id: str = ""
    balance_tokens: int = 0
    threshold: int = 0
```

---

## 11. Prometheus Metrics (`app/ai/metrics.py`)

```python
ai_requests_total = Counter("ai_requests_total", "Total AI requests", ["provider", "model", "status", "key_source"])
ai_tokens_total = Counter("ai_tokens_total", "Total tokens consumed", ["provider", "model", "token_type"])
ai_latency_seconds = Histogram("ai_latency_seconds", "AI request latency", ["provider", "model"])
ai_wallet_balance = Gauge("ai_wallet_balance_tokens", "Current wallet balance", ["tenant_id"])
ai_cost_usd_total = Counter("ai_cost_usd_total", "Total cost in USD", ["provider", "model"])
```

---

## 12. Configuration Additions (`app/config.py`)

```python
# AI Gateway
AI_ENABLED: bool = True
AI_REQUEST_TIMEOUT_SECONDS: int = 30
AI_MAX_TOKENS_PER_REQUEST: int = 128_000
AI_MAX_MESSAGES_PER_REQUEST: int = 100
AI_WALLET_MARGIN_MULTIPLIER: float = 1.15   # 15% platform margin
AI_WALLET_LOW_BALANCE_THRESHOLD: int = 1000  # Emit WalletBalanceLow event
AI_CACHE_ENABLED: bool = True
AI_CACHE_TTL_SECONDS: int = 3600
AI_DEFAULT_FALLBACK_ENABLED: bool = True

# Platform-managed provider keys (env vars)
AI_OPENAI_API_KEY: str = ""
AI_ANTHROPIC_API_KEY: str = ""
AI_GOOGLE_API_KEY: str = ""
AI_MISTRAL_API_KEY: str = ""
AI_DEEPSEEK_API_KEY: str = ""
AI_QWEN_API_KEY: str = ""
AI_ALEPH_ALPHA_API_KEY: str = ""
```

---

## 13. Scopes & Quota Integration

### New scopes (added to `settings.VALID_SCOPES`):
```python
"ai:read", "ai:write", "ai:admin"
```

### New quota metrics (added to `QuotaMetric`):
```python
AI_TOKENS_MONTH = "ai_tokens_month"
AI_REQUESTS_DAY = "ai_requests_day"
```

### Plan limits additions:
```python
"free":       { "ai_tokens_month": 10_000,    "ai_requests_day": 50 },
"starter":    { "ai_tokens_month": 500_000,   "ai_requests_day": 500 },
"pro":        { "ai_tokens_month": 5_000_000, "ai_requests_day": 5_000 },
"enterprise": { "ai_tokens_month": -1,        "ai_requests_day": -1 },  # unlimited
```

---

## 14. Celery Tasks (`app/ai/tasks.py`)

```python
@celery_app.task(bind=True, soft_time_limit=120, time_limit=180, acks_late=True)
def process_ai_completion(self, tenant_id: str, request_data: dict, job_id: str):
    """Async AI completion executed by Celery worker.
    Updates the Job record with result or error when done."""
```

---

## 15. Integration Points (Reusing Existing Infrastructure)

| Feature | Existing Component | How It's Used |
|---|---|---|
| Circuit breaker | `app.core.circuit_breaker.CircuitBreaker` | New `ai_breaker` instance, keyed by provider |
| Retry | `app.core.retry.retry` | Decorates LiteLLM calls with exp. backoff for transient errors |
| Cache | `app.core.cache.@cached` | Cache model catalog, key resolution, prompt templates |
| Encryption | `app.core.encryption.encrypt/decrypt` | Encrypt BYOK API keys at rest |
| Events | `app.core.events.emit/on` | Emit AI completion/wallet events |
| Quotas | `app.core.quotas.QuotaEnforcer` | Enforce ai_tokens_month, ai_requests_day |
| Rate limiting | `app.api.rate_limit` | Rate limit AI endpoints (per API key) |
| Idempotency | `app.core.idempotency` | Deduplicate async completion requests |
| Audit | `app.db.models.AuditLog` | Log provider key creation/deletion, wallet topups |
| Feature flags | `app.core.feature_flags` | `ai_enabled`, `ai_streaming_enabled` per tenant |
| Telemetry | `app.core.telemetry` | OTel spans for AI calls |
| Celery | `app.workers.celery_app` | Async AI completions, wallet sync, usage aggregation |
| Billing/Stripe | `app.billing.stripe_service` | Process wallet topup payments |

---

## 16. Dependencies Addition (`pyproject.toml`)

```toml
"litellm>=1.55,<2",        # Unified multi-provider LLM gateway
"tiktoken>=0.8,<1",        # OpenAI tokenizer (used by LiteLLM)
"sse-starlette>=2.0,<3",   # SSE support for FastAPI streaming
```

---

## 17. Implementation Order

### Phase 1: Foundation (files 1-5)
1. `app/ai/__init__.py` — package init
2. `app/ai/providers.py` — provider registry + model catalog
3. `app/ai/schemas.py` — all Pydantic schemas
4. DB models in `app/db/models.py` — add 5 new models
5. Alembic migration `a005_ai_infrastructure.py`

### Phase 2: Core Engine (files 6-10)
6. `app/ai/key_resolver.py` — BYOK + platform key resolution
7. `app/ai/wallet.py` — prepaid token wallet with Redis Lua
8. `app/ai/guardrails.py` — input validation + output filtering
9. `app/ai/cost.py` — token counting + cost calculation + margin
10. `app/ai/gateway.py` — core LiteLLM gateway with circuit breaker

### Phase 3: API & Integrations (files 11-15)
11. `app/ai/events.py` — domain events
12. `app/ai/metrics.py` — Prometheus counters/histograms
13. `app/ai/streaming.py` — SSE streaming helper
14. `app/ai/dependencies.py` — FastAPI dependencies (wallet check, quota, etc.)
15. `app/ai/tasks.py` — Celery tasks for async completions

### Phase 4: Routes & Config (files 16-18)
16. `app/config.py` — add AI settings
17. `app/core/quotas.py` — add AI quota metrics + plan limits
18. `app/api/v1/ai.py` — all API route handlers
19. `app/api/v1/__init__.py` — register AI router
20. `pyproject.toml` — add litellm, tiktoken, sse-starlette dependencies

### Phase 5: Tests
21. `tests/test_ai_gateway.py` — unit tests for gateway
22. `tests/test_ai_wallet.py` — unit tests for wallet
23. `tests/test_ai_api.py` — integration tests for API endpoints

---

## 18. Security Considerations

- BYOK API keys encrypted at rest via Fernet (AES-128-CBC + HMAC-SHA256)
- BYOK keys never returned in API responses (write-only)
- Wallet deductions are atomic (Redis Lua script prevents race conditions)
- Input guardrails prevent prompt injection patterns and budget blowout
- Output filtering for PII patterns (configurable per tenant)
- All AI operations audit-logged
- Circuit breaker prevents cascade failures from provider outages
- Rate limiting per API key prevents abuse
- Quota enforcement prevents runaway usage
- Tenant isolation via RLS context on all DB queries
- Request timeouts (30s default) prevent hanging connections
- No raw provider errors leaked to clients (sanitized error responses)
