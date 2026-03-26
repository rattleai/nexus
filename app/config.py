import warnings

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://app:app@localhost:5432/app"
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

    # Cloud Drive OAuth
    GOOGLE_DRIVE_CLIENT_ID: str = ""
    GOOGLE_DRIVE_CLIENT_SECRET: str = ""
    GOOGLE_DRIVE_REDIRECT_URI: str = ""
    DROPBOX_APP_KEY: str = ""
    DROPBOX_APP_SECRET: str = ""
    DROPBOX_REDIRECT_URI: str = ""
    ONEDRIVE_CLIENT_ID: str = ""
    ONEDRIVE_CLIENT_SECRET: str = ""
    ONEDRIVE_REDIRECT_URI: str = ""

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

    # Agent Memory
    AGENT_MEMORY_SHORT_TTL_SECONDS: int = 3600
    AGENT_MEMORY_SHORT_MAX_ENTRIES: int = 100
    AGENT_MEMORY_VECTOR_ENABLED: bool = False  # Requires pgvector extension
    AGENT_MEMORY_VECTOR_DIMENSIONS: int = 1536

    # Durable Event Bus (Redis Streams)
    EVENT_BUS_ENABLED: bool = True
    EVENT_BUS_STREAM_PREFIX: str = "events"
    EVENT_BUS_MAX_LEN: int = 100_000
    EVENT_BUS_CONSUMER_GROUP: str = "platform"
    EVENT_BUS_BLOCK_MS: int = 5000
    AGENT_RATE_LIMIT_WINDOW_SECONDS: int = 60
    OAUTH_CLIENT_CREDENTIALS_ENABLED: bool = False

    # Cloud Drive OAuth Integration
    GOOGLE_DRIVE_CLIENT_ID: str = ""
    GOOGLE_DRIVE_CLIENT_SECRET: str = ""
    GOOGLE_DRIVE_REDIRECT_URI: str = ""
    DROPBOX_APP_KEY: str = ""
    DROPBOX_APP_SECRET: str = ""
    DROPBOX_REDIRECT_URI: str = ""
    ONEDRIVE_CLIENT_ID: str = ""
    ONEDRIVE_CLIENT_SECRET: str = ""
    ONEDRIVE_REDIRECT_URI: str = ""

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
        "configurator:read", "configurator:write",
        "datasources:read", "datasources:write",
        "cloud-connections:read", "cloud-connections:write",
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
