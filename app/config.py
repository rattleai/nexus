import warnings

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    # Superuser URL for running Alembic migrations (CREATE TABLE, ALTER, RLS setup).
    # Falls back to DATABASE_URL when not set (dev convenience).
    DATABASE_MIGRATION_URL: str = ""
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # S3-compatible storage (Cloudflare R2)
    S3_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = "uploads"
    S3_REGION: str = "auto"

    # Application
    SECRET_KEY: str = "change-me-in-production"
    ENCRYPTION_KEY: str = ""  # Dedicated key for data-at-rest encryption (HKDF-derived)
    WEBHOOK_SIGNING_KEY: str = ""  # Dedicated key for webhook HMAC signatures
    ADMIN_KEY: str = ""  # Separate admin key — do NOT reuse SECRET_KEY
    DEBUG: bool = False
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8000"
    API_V1_PREFIX: str = "/api/v1"

    # Rate limiting (requests per window)
    RATE_LIMIT_DEFAULT: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_AUTH_ENDPOINTS: int = 10

    # Request size limits
    MAX_REQUEST_BODY_BYTES: int = 1_048_576  # 1 MB for JSON payloads
    MAX_UPLOAD_SIZE_BYTES: int = 52_428_800  # 50 MB for file uploads

    # Rate limiting for file uploads (per window)
    RATE_LIMIT_UPLOADS: int = 20

    # Caching
    CACHE_ENABLED: bool = True
    CACHE_DEFAULT_TTL: int = 300

    # OpenTelemetry
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "saas-platform"
    OTEL_EXPORTER_ENDPOINT: str = "http://localhost:4317"

    # User authentication (opt-in)
    AUTH_ENABLED: bool = False
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ALGORITHM: str = "RS256"
    JWT_PRIVATE_KEY: str = ""  # PEM-encoded RSA private key for RS256 JWT signing
    JWT_PUBLIC_KEY: str = ""   # PEM-encoded RSA public key for RS256 JWT verification
    JWT_PUBLIC_KEY_PREVIOUS: str = ""  # Previous public key for seamless key rotation (multi-key JWKS)
    OAUTH_GOOGLE_CLIENT_ID: str = ""
    OAUTH_GOOGLE_CLIENT_SECRET: str = ""
    OAUTH_GITHUB_CLIENT_ID: str = ""
    OAUTH_GITHUB_CLIENT_SECRET: str = ""

    # Email (Brevo / Sendinblue)
    BREVO_API_KEY: str = ""
    BREVO_SENDER_EMAIL: str = "noreply@example.com"
    BREVO_SENDER_NAME: str = "SaaS Platform"
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_EXPIRE_HOURS: int = 1
    APP_BASE_URL: str = "http://localhost:3000"

    # ── Connector System ─────────────────────────────────
    CONNECTOR_ENABLED: bool = True
    CONNECTOR_MCP_POOL_MAX_PER_SERVER: int = 3
    CONNECTOR_MCP_IDLE_TIMEOUT_SECONDS: int = 300
    CONNECTOR_MCP_CONNECT_TIMEOUT_SECONDS: int = 10
    CONNECTOR_MCP_REQUEST_TIMEOUT_SECONDS: int = 30
    CONNECTOR_HTTP_REQUEST_TIMEOUT_SECONDS: int = 30
    CONNECTOR_TOOL_CACHE_TTL_SECONDS: int = 300
    CONNECTOR_HEALTH_CHECK_INTERVAL_SECONDS: int = 300
    CONNECTOR_MAX_CONNECTIONS_PER_TENANT: int = 50
    CONNECTOR_CREDENTIAL_REFRESH_BUFFER_SECONDS: int = 300
    CONNECTOR_MAX_TOOL_OUTPUT_BYTES: int = 51200  # 50KB

    # Rate limiting (per user × per connector) — token bucket in Redis
    CONNECTOR_RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    CONNECTOR_RATE_LIMIT_BURST: int = 30

    # Signed registry verification (P1.3)
    CONNECTOR_REGISTRY_PUBLIC_KEY_PATH: str = ""
    CONNECTOR_REGISTRY_URL: str = "https://registry.modelcontextprotocol.io"
    CONNECTOR_REGISTRY_ALLOW_UNTRUSTED: bool = False

    # Durable execution (P1.4)
    CONNECTOR_DURABLE_EXECUTION_ENABLED: bool = True
    CONNECTOR_DURABLE_MAX_ATTEMPTS: int = 3
    CONNECTOR_DURABLE_RETRY_INITIAL_SECONDS: float = 1.0
    CONNECTOR_DURABLE_RETRY_BACKOFF: float = 2.0

    # Composio broker (P2.2)
    COMPOSIO_API_KEY: str = ""
    COMPOSIO_BASE_URL: str = "https://backend.composio.dev"
    # Default broker for connectors whose YAML does not specify one.
    # Composio is the recommended default: it gives tenants 500+ pre-integrated
    # SaaS tools with managed OAuth + refresh, and tokens never enter the
    # agent runtime. When COMPOSIO_API_KEY is unset, BrokerRouter falls back
    # to the in-house broker transparently so nothing breaks in dev.
    CONNECTOR_DEFAULT_BROKER: str = "composio"  # "composio" | "in_house"

    # HashiCorp Vault for in-house credentials (P2.3, optional)
    VAULT_ADDR: str = ""
    VAULT_TOKEN: str = ""
    VAULT_TRANSIT_KEY: str = "connector-tokens"

    # Cedar policy engine (P3.1)
    CONNECTOR_CEDAR_ENABLED: bool = False
    CONNECTOR_CEDAR_POLICY_DIR: str = "app/authz/policies"

    # Cloud-drive ingest (Dropbox / Google Drive / OneDrive → RAG)
    CLOUD_DRIVE_MAX_FILE_SIZE_MB: int = 50
    CLOUD_DRIVE_LIST_PAGE_SIZE: int = 100

    # A2A (P3.2)
    CONNECTOR_A2A_ENABLED: bool = False

    # Billing (Stripe)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # Database SSL mode for production connections
    DATABASE_SSL_MODE: str = ""  # Set to "require" in production for encrypted DB connections

    # Database sync URL (for Celery workers — avoids fragile string replacement)
    DATABASE_SYNC_URL: str = ""

    # Read replica (optional, for read-write splitting)
    DATABASE_READ_URL: str = ""

    # ── Mobile-First / PWA ───────────────────────────────
    # Web Push (VAPID) — required for push notifications
    VAPID_PRIVATE_KEY: str = ""
    VAPID_PUBLIC_KEY: str = ""
    VAPID_MAILTO: str = "admin@cadprice.com"

    # Firebase Cloud Messaging (for native mobile push)
    FIREBASE_SERVICE_ACCOUNT_JSON: str = ""

    # WebAuthn / FIDO2 (biometric authentication)
    WEBAUTHN_RP_ID: str = "localhost"
    WEBAUTHN_RP_NAME: str = "CAD Price"
    WEBAUTHN_ORIGIN: str = "http://localhost:3000"

    # CDN
    CDN_BASE_URL: str = ""
    CDN_IMAGE_TRANSFORM_PREFIX: str = ""  # e.g. /cdn-cgi/image/

    # ── AI Gateway ────────────────────────────────────────
    AI_ENABLED: bool = True
    AI_REQUEST_TIMEOUT_SECONDS: int = 30
    AI_MAX_TOKENS_PER_REQUEST: int = 128_000
    AI_MAX_MESSAGES_PER_REQUEST: int = 100
    AI_MAX_MESSAGE_LENGTH: int = 200_000

    # Margin multipliers — applied to provider cost (USD)
    # Platform keys: platform bears provider cost, higher margin
    # BYOK keys: tenant pays provider directly, lower infrastructure fee
    AI_MARGIN_PLATFORM_KEYS: float = 1.20   # 20% margin on platform-managed keys
    AI_MARGIN_BYOK_KEYS: float = 1.05       # 5% infrastructure fee on BYOK

    AI_WALLET_LOW_BALANCE_THRESHOLD: float = 5.00  # USD threshold for low balance warning

    # Auto-refill limits
    AI_AUTO_REFILL_MIN_AMOUNT: float = 5.00   # Minimum auto-refill amount in USD
    AI_AUTO_REFILL_MAX_AMOUNT: float = 500.00  # Maximum auto-refill amount in USD
    AI_CACHE_ENABLED: bool = True
    AI_CACHE_TTL_SECONDS: int = 3600
    AI_DEFAULT_FALLBACK_ENABLED: bool = True

    # Platform-managed provider API keys
    AI_OPENAI_API_KEY: str = ""
    AI_ANTHROPIC_API_KEY: str = ""
    AI_GOOGLE_API_KEY: str = ""
    AI_MISTRAL_API_KEY: str = ""
    AI_DEEPSEEK_API_KEY: str = ""
    AI_QWEN_API_KEY: str = ""
    AI_QWEN_API_BASE: str = ""              # Custom base URL for Qwen (e.g. DashScope)
    AI_ALEPH_ALPHA_API_KEY: str = ""
    AI_XAI_API_KEY: str = ""

    # Rate limiting for AI endpoints (per window)
    RATE_LIMIT_AI_REQUESTS: int = 60

    # ── MCP Server ───────────────────────────────────────────
    MCP_ENABLED: bool = False
    MCP_SERVER_NAME: str = "cadprice"
    MCP_TRANSPORT: str = "http"  # "stdio" or "http"
    MCP_HTTP_PORT: int = 8001
    MCP_LOG_TOOL_CALLS: bool = True
    MCP_RATE_LIMIT_REQUESTS: int = 300  # Max MCP requests per tenant per minute
    MCP_EXPOSE_API_ROUTES: bool = False  # Auto-expose FastAPI routes as MCP tools via fastapi-mcp (opt-in)

    # ── Agent / Bot API Enhancements ──────────────────────
    AGENT_HINTS_ENABLED: bool = True
    AGENT_RATE_LIMIT_REQUESTS: int = 300

    # ── Agent Execution Layer ──────────────────────────────
    AGENT_EXECUTION_ENABLED: bool = True
    AGENT_MAX_STEPS_PER_RUN: int = 50
    AGENT_MAX_DURATION_SECONDS: int = 300
    AGENT_MAX_TOKENS_PER_RUN: int = 100_000
    AGENT_SANDBOX_ENABLED: bool = False       # Opt-in code execution sandbox
    AGENT_SANDBOX_MEMORY_MB: int = 256
    AGENT_SANDBOX_CPU_SECONDS: int = 30
    AGENT_SANDBOX_TIMEOUT_SECONDS: int = 60
    AGENT_SANDBOX_NETWORK_ENABLED: bool = False
    AGENT_SESSION_MAX_MESSAGES: int = 200
    AGENT_TOOL_EXECUTION_TIMEOUT: int = 120  # Max seconds for individual tool execution
    AGENT_MAX_CONVERSATION_MESSAGES: int = 100  # Max messages in conversation window

    # Agent Resilience — configurable stale detection thresholds
    AGENT_HEARTBEAT_STALE_SECONDS: int = 300        # Mark RUNNING as stale if no heartbeat
    AGENT_PENDING_STALE_SECONDS: int = 600           # Mark PENDING as failed
    AGENT_LEGACY_STALE_SECONDS: int = 3600           # Fallback for pre-heartbeat instances

    # Agent Conversations (multi-turn interactive sessions)
    AGENT_SESSION_IDLE_TIMEOUT_SECONDS: int = 3600    # Default idle timeout for interactive sessions
    AGENT_SESSION_MAX_TURNS: int = 50                  # Max follow-up turns per conversation
    AGENT_SESSION_SLIDING_TTL: bool = True             # Extend session TTL on each turn
    AGENT_CONVERSATION_LOCK_TIMEOUT: int = 30          # Redis lock timeout for concurrent reply safety

    # Agent Memory
    AGENT_MEMORY_SHORT_TTL_SECONDS: int = 3600
    AGENT_MEMORY_SHORT_MAX_ENTRIES: int = 100
    AGENT_MEMORY_VECTOR_ENABLED: bool = False  # Requires pgvector extension
    AGENT_MEMORY_VECTOR_DIMENSIONS: int = 1536

    # ── RAG / Embedding Gateway ──────────────────────────────
    EMBEDDING_DEFAULT_PROVIDER: str = "openai"
    # Default model: text-embedding-3-small (MTEB ~62). For higher quality:
    #   voyage-4        (~67 MTEB, $0.06/1M tok, Matryoshka) — best cost/quality
    #   gemini-embedding-001 (~68 MTEB, $0.15/1M tok) — highest overall quality
    EMBEDDING_DEFAULT_MODEL: str = "text-embedding-3-small"
    EMBEDDING_COHERE_API_KEY: str = ""
    EMBEDDING_VOYAGE_API_KEY: str = ""
    EMBEDDING_LOCAL_URL: str = ""  # e.g., http://localhost:8080 for local models
    EMBEDDING_CACHE_ENABLED: bool = True
    EMBEDDING_CACHE_TTL_SECONDS: int = 86400  # 24 hours

    # RAG Chunking
    RAG_CHUNKING_STRATEGY: str = "fixed_size"  # fixed_size, recursive, markdown, semantic
    RAG_CHUNK_SIZE: int = 1000
    RAG_CHUNK_OVERLAP: int = 200
    RAG_SEMANTIC_SIMILARITY_THRESHOLD: float = 0.5

    # Vector quantization — controls which column is used for search.
    # Valid values (see VectorPrecision enum in app/db/models/datasource.py):
    #   "full"   = float32 vector(1536) — highest accuracy, 6 KB/vector
    #   "half"   = float16 halfvec(1536) — near-zero loss, 3 KB/vector (recommended)
    #   "binary" = 1-bit bit(1536) — 97% smaller but lower recall, 192 bytes/vector
    VECTOR_QUANTIZATION: str = "half"

    # Vector index type — controls which index is used for ANN search.
    # "hnsw"    = pgvector HNSW (default, no extra extension needed)
    # "diskann" = pgvectorscale StreamingDiskANN (10x+ throughput at 99% recall)
    VECTOR_INDEX_TYPE: str = "hnsw"

    # HNSW index build parameters — used when creating/rebuilding indexes.
    HNSW_M: int = 24              # edges per node (higher = better recall, larger index)
    HNSW_EF_CONSTRUCTION: int = 128  # build-time search width (higher = better index quality)

    # HNSW query-time tuning — controls recall vs. latency trade-off.
    # ef_search: candidates evaluated per query (pgvector default 40, too low for 1536-dim).
    # iterative_scan: re-enters index when filtered candidates are exhausted (pgvector >=0.8.0).
    HNSW_EF_SEARCH: int = 100
    PGVECTOR_ITERATIVE_SCAN: bool = True

    # DiskANN query-time tuning — search list size for recall optimization.
    DISKANN_QUERY_SEARCH_LIST_SIZE: int = 100

    # RAG Re-ranking
    RAG_RERANKER_PROVIDER: str = "none"  # none, cohere, cross_encoder
    RAG_RERANKER_MODEL: str = "rerank-v3.5"
    RAG_RERANKER_API_KEY: str = ""
    RAG_RERANKER_LOCAL_URL: str = ""
    RAG_RERANKER_TOP_K: int = 5

    # ── Advanced RAG Features ────────────────────────────────
    # Contextual Retrieval (Anthropic method) — prepend document context to chunks
    RAG_CONTEXTUAL_RETRIEVAL_ENABLED: bool = False
    RAG_CONTEXTUAL_MODEL: str = "claude-haiku-4-5-20251001"

    # Parent-child document retrieval — index small chunks, return parent context
    RAG_PARENT_CHILD_ENABLED: bool = False
    RAG_PARENT_CHUNK_SIZE: int = 2000
    RAG_CHILD_CHUNK_SIZE: int = 500

    # Query routing and decomposition
    RAG_QUERY_ROUTING_ENABLED: bool = False
    RAG_QUERY_DECOMPOSITION_ENABLED: bool = False

    # Semantic query cache (invalidated on data changes via event-driven mechanism)
    RAG_QUERY_CACHE_ENABLED: bool = False
    RAG_QUERY_CACHE_TTL_SECONDS: int = 1800  # 30 min (safe with event-driven invalidation)
    RAG_QUERY_CACHE_SIMILARITY_THRESHOLD: float = 0.95

    # Query analytics sampling rate (0.0-1.0, fraction of queries logged)
    RAG_QUERY_LOG_SAMPLE_RATE: float = 0.1

    # HyDE (Hypothetical Document Embeddings)
    RAG_HYDE_ENABLED: bool = False
    RAG_HYDE_MODEL: str = "claude-haiku-4-5-20251001"

    # Agentic RAG — multi-step retrieval with self-critique
    RAG_AGENTIC_ENABLED: bool = False
    RAG_AGENTIC_MAX_ITERATIONS: int = 3

    # Corrective RAG (CRAG) — document-level grading and filtering
    RAG_CRAG_ENABLED: bool = False

    # Graph RAG — knowledge graph extraction and retrieval
    RAG_GRAPH_ENABLED: bool = False

    # Late chunking (Jina-style) — requires LOCAL/Jina embedding provider
    RAG_LATE_CHUNKING_ENABLED: bool = False

    # ── Agent Security (Phase 0-2) ──────────────────────────
    # Phase 0 — DB Gateway
    AGENT_DB_MAX_QUERIES_PER_MINUTE: int = 60
    AGENT_DB_MAX_RESULT_ROWS: int = 1000
    AGENT_DB_MAX_RESULT_BYTES: int = 5_242_880  # 5 MB
    AGENT_DB_MAX_JOINS: int = 3
    AGENT_DB_STATEMENT_TIMEOUT_MS: int = 10_000
    AGENT_DB_POOL_PARTITION_PCT: int = 40  # % of pool reserved for agents

    # Phase 0 — Prompt Firewall
    PROMPT_FIREWALL_ENABLED: bool = True
    PROMPT_FIREWALL_CLASSIFIER_ENABLED: bool = False  # LLM classifier (costs tokens)
    PROMPT_FIREWALL_CLASSIFIER_MODEL: str = "claude-haiku-4-5-20251001"
    PROMPT_FIREWALL_CANARY_ENABLED: bool = True
    PROMPT_FIREWALL_FAIL_MODE: str = "block"  # "log" or "block"

    # Phase 1 — Sandbox
    AGENT_SANDBOX_BACKEND: str = "auto"  # "nsjail", "subprocess", "auto"
    AGENT_SANDBOX_STRICT: bool = True  # Reject if nsjail unavailable

    # Phase 1 — A2A Security
    AGENT_A2A_SIGNING_ENABLED: bool = True
    AGENT_A2A_ENCRYPTION_ENABLED: bool = True
    AGENT_A2A_LEGACY_DECRYPT: bool = True              # Allow no-AAD fallback for legacy messages (set False after migration)

    # Phase 1 — Tool Verification
    AGENT_TOOL_SCHEMA_VERIFICATION: bool = True
    AGENT_TOOL_BEHAVIORAL_MONITORING: bool = True

    # Phase 2 — Threat Detection
    AGENT_THREAT_DETECTION_ENABLED: bool = True
    AGENT_THREAT_ANOMALY_WARN_SIGMA: float = 2.0
    AGENT_THREAT_ANOMALY_SUSPEND_SIGMA: float = 3.0

    # Phase 2 — Data Classification
    DATA_CLASSIFICATION_ENABLED: bool = True
    DATA_CLASSIFICATION_DEFAULT_LEVEL: str = "INTERNAL"

    # Durable Event Bus (Redis Streams)
    EVENT_BUS_ENABLED: bool = True
    EVENT_BUS_STREAM_PREFIX: str = "events"
    EVENT_BUS_MAX_LEN: int = 100_000
    EVENT_BUS_CONSUMER_GROUP: str = "platform"
    EVENT_BUS_BLOCK_MS: int = 5000
    AGENT_RATE_LIMIT_WINDOW_SECONDS: int = 60
    AGENT_RATE_LIMIT_FAIL_OPEN: bool = False           # If True, allow requests when Redis rate limiter unavailable (dev only)
    OAUTH_CLIENT_CREDENTIALS_ENABLED: bool = False

    # ── Application plugin feature flags ──
    # Each app plugin checks its flag via the plugin registry.
    # Listed here for documentation; actual gating is in app.plugins.registry.
    APP_CPQ_ENABLED: bool = True

    # (Connector OAuth credentials are stored per-connector in connector_definitions.)

    # Allowed scope values for API keys
    VALID_SCOPES: list[str] = [
        "jobs:read", "jobs:write",
        "files:read", "files:write",
        "api-keys:read", "api-keys:write",
        "team:read", "team:write",
        "webhooks:read", "webhooks:write",
        "billing:read", "billing:write",
        "audit:read",
        "ai:read", "ai:write", "ai:admin",
        "mcp:read", "mcp:write",
        "agents:read", "agents:write", "agents:admin", "agents:execute",
        "connections:read", "connections:write", "connections:admin",
        # App-specific scopes are contributed dynamically via plugins.
        # See app.plugins.registry — scopes are appended after discovery.
    ]

    # Scopes that must never be granted to API keys.  These control critical
    # infrastructure (key management, audit trail) that should only be
    # accessible from the application UI via JWT-authenticated sessions.
    INFRASTRUCTURE_SCOPES: frozenset[str] = frozenset({
        "api-keys:read",
        "api-keys:write",
        "audit:read",
    })

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.OAUTH_GOOGLE_CLIENT_ID and self.OAUTH_GOOGLE_CLIENT_SECRET)

    @property
    def github_oauth_configured(self) -> bool:
        return bool(self.OAUTH_GITHUB_CLIENT_ID and self.OAUTH_GITHUB_CLIENT_SECRET)

    @property
    def storage_configured(self) -> bool:
        return bool(self.S3_ENDPOINT_URL and self.S3_ACCESS_KEY_ID and self.S3_SECRET_ACCESS_KEY)

    @property
    def sync_database_url(self) -> str:
        """Get synchronous DB URL for Celery workers.

        Uses DATABASE_SYNC_URL if set, otherwise derives from DATABASE_URL
        by replacing the asyncpg driver with psycopg2.
        """
        if self.DATABASE_SYNC_URL:
            return self.DATABASE_SYNC_URL
        return self.DATABASE_URL.replace("+asyncpg", "")

    @property
    def email_configured(self) -> bool:
        return bool(self.BREVO_API_KEY)

    @property
    def stripe_configured(self) -> bool:
        return bool(self.STRIPE_SECRET_KEY)

    @property
    def ai_configured(self) -> bool:
        """True if at least one platform-managed AI provider key is set."""
        return bool(
            self.AI_OPENAI_API_KEY
            or self.AI_ANTHROPIC_API_KEY
            or self.AI_GOOGLE_API_KEY
            or self.AI_MISTRAL_API_KEY
            or self.AI_DEEPSEEK_API_KEY
            or self.AI_QWEN_API_KEY
            or self.AI_ALEPH_ALPHA_API_KEY
            or self.AI_XAI_API_KEY
        )


settings = Settings()


def validate_settings() -> None:
    """Validate critical settings on startup. Call from lifespan."""
    if settings.SECRET_KEY == "change-me-in-production":
        if settings.DEBUG:
            warnings.warn("SECRET_KEY is using the default value — not safe for production", stacklevel=2)
        else:
            raise RuntimeError("SECRET_KEY must be set to a unique value in production (DEBUG=false)")

    if not settings.ADMIN_KEY:
        if settings.DEBUG:
            warnings.warn("ADMIN_KEY is not set — admin endpoints will be inaccessible", stacklevel=2)
        else:
            raise RuntimeError("ADMIN_KEY must be set in production (DEBUG=false)")

    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
    if "*" in origins:
        raise RuntimeError("CORS_ORIGINS must not be '*' — specify explicit origins")

    if not settings.WEBHOOK_SIGNING_KEY:
        if settings.DEBUG:
            warnings.warn(
                "WEBHOOK_SIGNING_KEY is not set — webhook signing will be unavailable.",
                stacklevel=2,
            )
        else:
            raise RuntimeError(
                "WEBHOOK_SIGNING_KEY must be set in production (DEBUG=false). "
                "Never reuse SECRET_KEY for webhook signatures."
            )

    if not settings.ENCRYPTION_KEY:
        if settings.DEBUG:
            warnings.warn(
                "ENCRYPTION_KEY is not set — falling back to SECRET_KEY for encryption. "
                "Set a dedicated ENCRYPTION_KEY in production so that JWT key rotation "
                "does not break encrypted data at rest.",
                stacklevel=2,
            )
        else:
            raise RuntimeError(
                "ENCRYPTION_KEY must be set in production (DEBUG=false). "
                "Use a unique high-entropy value separate from SECRET_KEY."
            )

    # JWT asymmetric key validation
    if settings.JWT_ALGORITHM in ("RS256", "ES256"):
        if not settings.JWT_PRIVATE_KEY or not settings.JWT_PUBLIC_KEY:
            if settings.DEBUG:
                warnings.warn(
                    f"JWT_ALGORITHM is {settings.JWT_ALGORITHM} but JWT_PRIVATE_KEY/JWT_PUBLIC_KEY are not set. "
                    "Falling back to HS256 with SECRET_KEY. Set RSA keys for production.",
                    stacklevel=2,
                )
            else:
                raise RuntimeError(
                    f"JWT_ALGORITHM is {settings.JWT_ALGORITHM} — JWT_PRIVATE_KEY and JWT_PUBLIC_KEY must be set "
                    "in production. Generate with: openssl genrsa -out private.pem 2048 && "
                    "openssl rsa -in private.pem -pubout -out public.pem"
                )

    # Database SSL in production — enforce like other critical settings
    if not settings.DEBUG and not settings.DATABASE_SSL_MODE:
        raise RuntimeError(
            "DATABASE_SSL_MODE is not set. Set to 'verify-full' (recommended) or 'require' "
            "in production for encrypted DB connections."
        )
    elif not settings.DEBUG and settings.DATABASE_SSL_MODE == "require":
        warnings.warn(
            "DATABASE_SSL_MODE='require' encrypts traffic but does NOT verify the server certificate. "
            "Consider 'verify-full' for MITM protection.",
            stacklevel=2,
        )

    if not settings.storage_configured:
        warnings.warn(
            "S3 storage credentials not configured (S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY). "
            "File upload/download will not work.",
            stacklevel=2,
        )

    # ── Agent Security Configuration Validation ──────────────────
    _validate_security_config()


def _validate_security_config() -> None:
    """Validate agent security configuration at startup."""
    errors: list[str] = []

    # ── RAG / Vector config validation ────────────────────────
    if settings.VECTOR_QUANTIZATION not in ("full", "half", "binary"):
        errors.append(
            f"VECTOR_QUANTIZATION must be 'full', 'half', or 'binary', "
            f"got '{settings.VECTOR_QUANTIZATION}'"
        )
    if settings.RAG_CHUNKING_STRATEGY not in (
        "fixed_size", "recursive", "markdown", "semantic", "late",
    ):
        errors.append(
            f"RAG_CHUNKING_STRATEGY must be fixed_size|recursive|markdown|semantic|late, "
            f"got '{settings.RAG_CHUNKING_STRATEGY}'"
        )
    if settings.RAG_RERANKER_PROVIDER not in ("none", "cohere", "cross_encoder"):
        errors.append(
            f"RAG_RERANKER_PROVIDER must be none|cohere|cross_encoder, "
            f"got '{settings.RAG_RERANKER_PROVIDER}'"
        )
    if settings.VECTOR_INDEX_TYPE not in ("hnsw", "diskann"):
        errors.append(
            f"VECTOR_INDEX_TYPE must be 'hnsw' or 'diskann', "
            f"got '{settings.VECTOR_INDEX_TYPE}'"
        )
    if not (0.0 <= settings.RAG_QUERY_LOG_SAMPLE_RATE <= 1.0):
        errors.append("RAG_QUERY_LOG_SAMPLE_RATE must be between 0.0 and 1.0")
    if not (0.0 < settings.RAG_QUERY_CACHE_SIMILARITY_THRESHOLD <= 1.0):
        errors.append("RAG_QUERY_CACHE_SIMILARITY_THRESHOLD must be between 0.0 and 1.0")

    # Validate enum values
    if settings.PROMPT_FIREWALL_FAIL_MODE not in ("log", "block"):
        errors.append(
            f"PROMPT_FIREWALL_FAIL_MODE must be 'log' or 'block', "
            f"got '{settings.PROMPT_FIREWALL_FAIL_MODE}'"
        )

    if settings.DATA_CLASSIFICATION_DEFAULT_LEVEL not in (
        "PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED",
    ):
        errors.append(
            f"Invalid DATA_CLASSIFICATION_DEFAULT_LEVEL: "
            f"'{settings.DATA_CLASSIFICATION_DEFAULT_LEVEL}'"
        )

    if settings.AGENT_SANDBOX_BACKEND not in ("nsjail", "subprocess", "auto"):
        errors.append(
            f"AGENT_SANDBOX_BACKEND must be 'nsjail', 'subprocess', or 'auto', "
            f"got '{settings.AGENT_SANDBOX_BACKEND}'"
        )

    # Validate ranges
    if settings.AGENT_DB_STATEMENT_TIMEOUT_MS < 100 or settings.AGENT_DB_STATEMENT_TIMEOUT_MS > 300_000:
        errors.append("AGENT_DB_STATEMENT_TIMEOUT_MS must be between 100 and 300000")

    if settings.AGENT_THREAT_ANOMALY_WARN_SIGMA >= settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA:
        errors.append(
            "AGENT_THREAT_ANOMALY_WARN_SIGMA must be less than SUSPEND_SIGMA"
        )

    # Production security posture warnings
    if not settings.DEBUG:
        if not settings.PROMPT_FIREWALL_ENABLED:
            warnings.warn(
                "PROMPT_FIREWALL_ENABLED is False in production — "
                "prompt injection attempts will not be detected.",
                stacklevel=3,
            )
        if settings.PROMPT_FIREWALL_FAIL_MODE != "block":
            warnings.warn(
                "PROMPT_FIREWALL_FAIL_MODE is not 'block' in production — "
                "prompt injection attempts will only be logged, not blocked.",
                stacklevel=3,
            )
        if not settings.AGENT_THREAT_DETECTION_ENABLED:
            warnings.warn(
                "AGENT_THREAT_DETECTION_ENABLED is False in production — "
                "anomalous agent behavior will not be detected.",
                stacklevel=3,
            )
        if not settings.AGENT_A2A_ENCRYPTION_ENABLED:
            warnings.warn(
                "AGENT_A2A_ENCRYPTION_ENABLED is False in production — "
                "agent-to-agent messages will not be encrypted.",
                stacklevel=3,
            )

    if errors:
        raise RuntimeError(
            "Agent security configuration errors:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
