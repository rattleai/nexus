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

    # Allowed scope values for API keys
    VALID_SCOPES: list[str] = [
        "jobs:read", "jobs:write",
        "files:read", "files:write",
        "api-keys:read", "api-keys:write",
    ]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def storage_configured(self) -> bool:
        return bool(self.S3_ENDPOINT_URL and self.S3_ACCESS_KEY_ID and self.S3_SECRET_ACCESS_KEY)


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
            warnings.warn("ADMIN_KEY is not set — using SECRET_KEY as fallback (not safe for production)", stacklevel=2)
        else:
            raise RuntimeError("ADMIN_KEY must be set in production (DEBUG=false)")

    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
    if "*" in origins:
        raise RuntimeError("CORS_ORIGINS must not be '*' — specify explicit origins")

    if not settings.WEBHOOK_SIGNING_KEY and not settings.DEBUG:
        warnings.warn(
            "WEBHOOK_SIGNING_KEY is not set — falling back to SECRET_KEY for webhook signatures. "
            "Set a dedicated WEBHOOK_SIGNING_KEY in production.",
            stacklevel=2,
        )

    if not settings.storage_configured:
        warnings.warn(
            "S3 storage credentials not configured (S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY). "
            "File upload/download will not work.",
            stacklevel=2,
        )
