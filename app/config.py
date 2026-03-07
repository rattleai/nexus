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
    JWT_ALGORITHM: str = "HS256"
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

    # Billing (Stripe)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

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

    # Margin multipliers — applied to raw token consumption
    # Platform keys: platform bears provider cost, higher margin
    # BYOK keys: tenant pays provider directly, lower infrastructure fee
    AI_MARGIN_PLATFORM_KEYS: float = 1.20   # 20% margin on platform-managed keys
    AI_MARGIN_BYOK_KEYS: float = 1.05       # 5% infrastructure fee on BYOK

    AI_WALLET_LOW_BALANCE_THRESHOLD: int = 1000
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

    # Rate limiting for AI endpoints (per window)
    RATE_LIMIT_AI_REQUESTS: int = 60

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
    ]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

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

    if not settings.storage_configured:
        warnings.warn(
            "S3 storage credentials not configured (S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY). "
            "File upload/download will not work.",
            stacklevel=2,
        )
