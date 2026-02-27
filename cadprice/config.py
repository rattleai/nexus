from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://cadprice:cadprice@localhost:5432/cadprice"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # S3-compatible storage (Cloudflare R2)
    S3_ENDPOINT_URL: str = "https://ACCOUNT_ID.r2.cloudflarestorage.com"
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = "cadprice"
    S3_REGION: str = "auto"

    # Application
    SECRET_KEY: str = "change-me-in-production"
    DEBUG: bool = False
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8000"
    API_V1_PREFIX: str = "/api/v1"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
