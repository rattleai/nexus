"""Provider registry and model catalog.

Maps model identifiers to LiteLLM model strings, provider metadata,
and capability flags. Used by the gateway to route requests and by
the API to expose available models.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import settings
from app.db.models.ai import AIProvider


@dataclass(frozen=True)
class ModelInfo:
    """Metadata for a single AI model."""

    provider: AIProvider
    litellm_model: str
    display_name: str
    max_input_tokens: int
    max_output_tokens: int
    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_vision: bool = False
    deprecated: bool = False


# ── Model Catalog ─────────────────────────────────────────
# The litellm_model string is what gets passed to litellm.acompletion().
# LiteLLM uses provider prefixes to route: "anthropic/", "gemini/", etc.

MODEL_CATALOG: dict[str, ModelInfo] = {
    # OpenAI
    "gpt-4o": ModelInfo(
        provider=AIProvider.OPENAI,
        litellm_model="gpt-4o",
        display_name="GPT-4o",
        max_input_tokens=128_000,
        max_output_tokens=16_384,
        supports_function_calling=True,
        supports_vision=True,
    ),
    "gpt-4o-mini": ModelInfo(
        provider=AIProvider.OPENAI,
        litellm_model="gpt-4o-mini",
        display_name="GPT-4o Mini",
        max_input_tokens=128_000,
        max_output_tokens=16_384,
        supports_function_calling=True,
        supports_vision=True,
    ),
    "gpt-4-turbo": ModelInfo(
        provider=AIProvider.OPENAI,
        litellm_model="gpt-4-turbo",
        display_name="GPT-4 Turbo",
        max_input_tokens=128_000,
        max_output_tokens=4_096,
        supports_function_calling=True,
        supports_vision=True,
    ),
    "o1": ModelInfo(
        provider=AIProvider.OPENAI,
        litellm_model="o1",
        display_name="o1",
        max_input_tokens=200_000,
        max_output_tokens=100_000,
        supports_streaming=False,
    ),
    "o1-mini": ModelInfo(
        provider=AIProvider.OPENAI,
        litellm_model="o1-mini",
        display_name="o1-mini",
        max_input_tokens=128_000,
        max_output_tokens=65_536,
        supports_streaming=False,
    ),
    # Anthropic
    "claude-opus-4-20250514": ModelInfo(
        provider=AIProvider.ANTHROPIC,
        litellm_model="anthropic/claude-opus-4-20250514",
        display_name="Claude Opus 4",
        max_input_tokens=200_000,
        max_output_tokens=32_000,
        supports_function_calling=True,
        supports_vision=True,
    ),
    "claude-sonnet-4-20250514": ModelInfo(
        provider=AIProvider.ANTHROPIC,
        litellm_model="anthropic/claude-sonnet-4-20250514",
        display_name="Claude Sonnet 4",
        max_input_tokens=200_000,
        max_output_tokens=16_000,
        supports_function_calling=True,
        supports_vision=True,
    ),
    "claude-haiku-4-5-20251001": ModelInfo(
        provider=AIProvider.ANTHROPIC,
        litellm_model="anthropic/claude-haiku-4-5-20251001",
        display_name="Claude Haiku 4.5",
        max_input_tokens=200_000,
        max_output_tokens=8_192,
        supports_function_calling=True,
        supports_vision=True,
    ),
    # Google Gemini
    "gemini-2.0-flash": ModelInfo(
        provider=AIProvider.GOOGLE,
        litellm_model="gemini/gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        max_input_tokens=1_048_576,
        max_output_tokens=8_192,
        supports_function_calling=True,
        supports_vision=True,
    ),
    "gemini-2.0-pro": ModelInfo(
        provider=AIProvider.GOOGLE,
        litellm_model="gemini/gemini-2.0-pro",
        display_name="Gemini 2.0 Pro",
        max_input_tokens=1_048_576,
        max_output_tokens=8_192,
        supports_function_calling=True,
        supports_vision=True,
    ),
    # Mistral
    "mistral-large-latest": ModelInfo(
        provider=AIProvider.MISTRAL,
        litellm_model="mistral/mistral-large-latest",
        display_name="Mistral Large",
        max_input_tokens=128_000,
        max_output_tokens=4_096,
        supports_function_calling=True,
    ),
    "mistral-small-latest": ModelInfo(
        provider=AIProvider.MISTRAL,
        litellm_model="mistral/mistral-small-latest",
        display_name="Mistral Small",
        max_input_tokens=128_000,
        max_output_tokens=4_096,
        supports_function_calling=True,
    ),
    # DeepSeek
    "deepseek-chat": ModelInfo(
        provider=AIProvider.DEEPSEEK,
        litellm_model="deepseek/deepseek-chat",
        display_name="DeepSeek Chat (V3)",
        max_input_tokens=64_000,
        max_output_tokens=8_192,
        supports_function_calling=True,
    ),
    "deepseek-reasoner": ModelInfo(
        provider=AIProvider.DEEPSEEK,
        litellm_model="deepseek/deepseek-reasoner",
        display_name="DeepSeek Reasoner (R1)",
        max_input_tokens=64_000,
        max_output_tokens=8_192,
    ),
    # Qwen
    "qwen-max": ModelInfo(
        provider=AIProvider.QWEN,
        litellm_model="openai/qwen-max",
        display_name="Qwen Max",
        max_input_tokens=32_000,
        max_output_tokens=8_192,
        supports_function_calling=True,
    ),
    "qwen-turbo": ModelInfo(
        provider=AIProvider.QWEN,
        litellm_model="openai/qwen-turbo",
        display_name="Qwen Turbo",
        max_input_tokens=128_000,
        max_output_tokens=8_192,
        supports_function_calling=True,
    ),
    # Aleph Alpha
    "luminous-supreme": ModelInfo(
        provider=AIProvider.ALEPH_ALPHA,
        litellm_model="aleph_alpha/luminous-supreme",
        display_name="Luminous Supreme",
        max_input_tokens=2_048,
        max_output_tokens=2_048,
    ),
    # X.AI (Grok)
    "grok-4": ModelInfo(
        provider=AIProvider.XAI,
        litellm_model="xai/grok-4",
        display_name="Grok 4",
        max_input_tokens=256_000,
        max_output_tokens=16_384,
        supports_function_calling=True,
        supports_vision=True,
    ),
    "grok-4-1-fast-reasoning": ModelInfo(
        provider=AIProvider.XAI,
        litellm_model="xai/grok-4-1-fast-reasoning",
        display_name="Grok 4.1 Fast (Reasoning)",
        max_input_tokens=2_000_000,
        max_output_tokens=16_384,
        supports_function_calling=True,
        supports_vision=True,
    ),
    "grok-4-1-fast-non-reasoning": ModelInfo(
        provider=AIProvider.XAI,
        litellm_model="xai/grok-4-1-fast-non-reasoning",
        display_name="Grok 4.1 Fast",
        max_input_tokens=2_000_000,
        max_output_tokens=16_384,
        supports_function_calling=True,
        supports_vision=True,
    ),
    "grok-3-mini": ModelInfo(
        provider=AIProvider.XAI,
        litellm_model="xai/grok-3-mini",
        display_name="Grok 3 Mini",
        max_input_tokens=131_072,
        max_output_tokens=8_192,
        supports_function_calling=True,
    ),
}


# ── Provider → Platform env var mapping ───────────────────

PROVIDER_ENV_MAP: dict[AIProvider, str] = {
    AIProvider.OPENAI: "AI_OPENAI_API_KEY",
    AIProvider.ANTHROPIC: "AI_ANTHROPIC_API_KEY",
    AIProvider.GOOGLE: "AI_GOOGLE_API_KEY",
    AIProvider.MISTRAL: "AI_MISTRAL_API_KEY",
    AIProvider.DEEPSEEK: "AI_DEEPSEEK_API_KEY",
    AIProvider.QWEN: "AI_QWEN_API_KEY",
    AIProvider.ALEPH_ALPHA: "AI_ALEPH_ALPHA_API_KEY",
    AIProvider.XAI: "AI_XAI_API_KEY",
}

# ── Default Fallback Chains ──────────────────────────────
# When a model's provider is down, try these alternatives in order.

DEFAULT_FALLBACK_CHAINS: dict[str, list[str]] = {
    "gpt-4o": ["claude-sonnet-4-20250514", "gemini-2.0-flash"],
    "gpt-4o-mini": ["claude-haiku-4-5-20251001", "mistral-small-latest"],
    "claude-sonnet-4-20250514": ["gpt-4o", "gemini-2.0-pro"],
    "claude-haiku-4-5-20251001": ["gpt-4o-mini", "mistral-small-latest"],
    "gemini-2.0-flash": ["gpt-4o-mini", "claude-haiku-4-5-20251001"],
    "mistral-large-latest": ["gpt-4o", "claude-sonnet-4-20250514"],
    "deepseek-chat": ["gpt-4o-mini", "mistral-small-latest"],
    "grok-4": ["gpt-4o", "claude-sonnet-4-20250514"],
    "grok-3-mini": ["gpt-4o-mini", "mistral-small-latest"],
}


def get_model_info(model_id: str) -> ModelInfo | None:
    """Look up model metadata by ID."""
    return MODEL_CATALOG.get(model_id)


def get_platform_api_key(provider: AIProvider) -> str:
    """Get the platform-managed API key for a provider from settings."""
    attr = PROVIDER_ENV_MAP.get(provider)
    if not attr:
        return ""
    # Map env var name to Settings attribute name (they match)
    return getattr(settings, attr, "")


def list_available_providers() -> list[AIProvider]:
    """Return providers that have a platform-managed key configured."""
    return [p for p in AIProvider if get_platform_api_key(p)]
