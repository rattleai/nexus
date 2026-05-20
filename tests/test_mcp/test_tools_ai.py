"""Tests for MCP AI tools."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.tools.ai import ai_complete, ai_get_usage, ai_list_models


def _make_tenant():
    return MagicMock(
        id=uuid.uuid4(),
        name="Test",
        is_active=True,
        settings={},
    )


@pytest.mark.asyncio
async def test_ai_list_models():
    """Test listing available models."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_catalog = {
        "gpt-4o": MagicMock(
            deprecated=False,
            provider=MagicMock(value="openai"),
            display_name="GPT-4o",
            max_input_tokens=128000,
            max_output_tokens=4096,
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision=True,
        ),
    }

    with (
        patch("app.mcp.tools.ai.MODEL_CATALOG", mock_catalog),
        patch("app.ai.key_resolver.check_key_availability", new_callable=AsyncMock, return_value=(True, "platform")),
    ):
        result = await ai_list_models(tenant=tenant, db=mock_db)

    assert len(result) == 1
    assert result[0]["model_id"] == "gpt-4o"
    assert result[0]["available"] is True


@pytest.mark.asyncio
async def test_ai_list_models_skips_deprecated():
    """Test that deprecated models are excluded."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_catalog = {
        "old-model": MagicMock(deprecated=True),
    }

    with patch("app.mcp.tools.ai.MODEL_CATALOG", mock_catalog):
        result = await ai_list_models(tenant=tenant, db=mock_db)

    assert len(result) == 0


@pytest.mark.asyncio
async def test_ai_complete_unknown_model():
    """Test that unknown models raise an error."""
    from app.mcp.errors import McpError

    tenant = _make_tenant()
    mock_db = AsyncMock()

    with (
        patch("app.mcp.tools.ai.get_model_info", return_value=None),
        pytest.raises(McpError, match="Unknown model"),
    ):
        await ai_complete(
            model="nonexistent",
            messages=[{"role": "user", "content": "hello"}],
            tenant=tenant,
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_ai_complete_success():
    """Test successful AI completion."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_model_info = MagicMock(
        provider=MagicMock(value="openai"),
    )
    mock_result = MagicMock(
        id="test-id",
        model="gpt-4o",
        content="Hello!",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        billed_tokens=18,
        billed_amount_usd=0.0012,
        cost_usd=0.001,
        latency_ms=100,
        key_source="platform",
        finish_reason="stop",
        provider="openai",
    )

    with (
        patch("app.mcp.tools.ai.get_model_info", return_value=mock_model_info),
        patch("app.mcp.tools.ai.validate_input", return_value=[]),
        patch("app.mcp.tools.ai.resolve_api_key", new_callable=AsyncMock, return_value=("key", "platform")),
        patch("app.mcp.tools.ai.ai_gateway") as mock_gateway,
        patch("app.mcp.tools.ai.wallet_service") as mock_wallet,
    ):
        mock_gateway.completion = AsyncMock(return_value=mock_result)
        mock_wallet.deduct = AsyncMock(return_value=None)

        result = await ai_complete(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hello"}],
            tenant=tenant,
            db=mock_db,
        )

    assert result["content"] == "Hello!"
    assert result["model"] == "gpt-4o"
    assert result["total_tokens"] == 15


@pytest.mark.asyncio
async def test_ai_get_usage():
    """Test getting AI usage stats."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_row = MagicMock(
        total_requests=10,
        total_tokens=5000,
        total_prompt_tokens=3000,
        total_completion_tokens=2000,
        total_cost_usd=0.5,
    )
    mock_result = MagicMock()
    mock_result.one.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await ai_get_usage(days=7, tenant=tenant, db=mock_db)

    assert result["total_requests"] == 10
    assert result["total_tokens"] == 5000
    assert result["days"] == 7
