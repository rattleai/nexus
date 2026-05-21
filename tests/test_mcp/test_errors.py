"""Tests for MCP error mapping."""

from app.mcp.errors import McpError, auth_error, insufficient_balance_error, not_found_error, tool_error


def test_tool_error_basic():
    err = tool_error("Something went wrong")
    assert isinstance(err, McpError)
    assert "Something went wrong" in str(err)


def test_tool_error_with_hint():
    err = tool_error("Bad input", hint="Try using valid JSON")
    assert "Bad input" in str(err)
    assert "Try using valid JSON" in str(err)


def test_auth_error():
    err = auth_error()
    assert isinstance(err, McpError)
    assert "Authentication failed" in str(err)


def test_not_found_error():
    err = not_found_error("Job")
    assert "Job not found" in str(err)


def test_insufficient_balance_error():
    err = insufficient_balance_error(42)
    assert "42" in str(err)
    assert "Insufficient" in str(err)
