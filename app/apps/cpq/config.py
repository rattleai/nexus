"""CPQ plugin configuration.

Settings are loaded from environment variables with the ``CPQ_`` prefix.
Access via ``cpq_settings`` singleton or through the plugin's
``get_plugin_config()`` method.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class CPQSettings(BaseSettings):
    """CPQ-specific settings, loaded from ``CPQ_*`` env vars."""

    # Engine limits
    MAX_CHARACTERISTICS_PER_PRODUCT: int = 200
    MAX_BOM_DEPTH: int = 10
    MAX_CONSTRAINT_RULES_PER_PRODUCT: int = 500
    CONSTRAINT_EVALUATION_TIMEOUT_SECONDS: int = 5
    MAX_VARIANTS_PER_PRODUCT: int = 10_000

    # Caching
    ENABLE_PRICING_CACHE: bool = True
    PRICING_CACHE_TTL_SECONDS: int = 3600

    # Rate limits
    MAX_CONCURRENT_CONFIGURATIONS: int = 100

    # Datasource processing
    DATASOURCE_PROCESSING_TIMEOUT_SECONDS: int = 300

    model_config = {"env_prefix": "CPQ_", "env_file": ".env", "extra": "ignore"}


cpq_settings = CPQSettings()
