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

    if not settings.storage_configured:
        warnings.warn(
            "S3 storage credentials not configured (S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY). "
            "File upload/download will not work.",
            stacklevel=2,
        )
