"""Tests for agent-aware rate limiting."""

from unittest.mock import MagicMock

from app.api.rate_limit import _is_agent_request


def _make_request(user_agent: str = "", agent_name: str | None = None) -> MagicMock:
    headers = {"User-Agent": user_agent}
    if agent_name:
        headers["X-Agent-Name"] = agent_name
    request = MagicMock()
    request.headers = headers
    return request


def test_detect_agent_by_user_agent():
    request = _make_request(user_agent="mcp-client/1.0")
    assert _is_agent_request(request) is True


def test_detect_agent_claude_code():
    request = _make_request(user_agent="claude-code/1.2.3")
    assert _is_agent_request(request) is True


def test_detect_agent_by_header():
    request = _make_request(agent_name="my-bot")
    assert _is_agent_request(request) is True


def test_not_agent_browser():
    request = _make_request(user_agent="Mozilla/5.0")
    assert _is_agent_request(request) is False


def test_not_agent_empty():
    request = _make_request()
    assert _is_agent_request(request) is False


def test_detect_agent_cadprice_cli():
    request = _make_request(user_agent="cadprice-cli/0.1.0")
    assert _is_agent_request(request) is True


def test_detect_agent_openai():
    request = _make_request(user_agent="openai-agent/2.0")
    assert _is_agent_request(request) is True
