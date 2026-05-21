"""Tests for MCP server initialization and tool registration."""

import pytest

fastmcp = pytest.importorskip("fastmcp", reason="fastmcp package not installed")


def test_create_mcp_server():
    """Test that the MCP server creates successfully with all tools registered."""
    from app.mcp.server import create_mcp_server

    mcp = create_mcp_server()

    # Verify the server was created
    assert mcp is not None
    assert mcp.name == "nxs"


@pytest.mark.asyncio
async def test_mcp_server_has_tools():
    """Test that the MCP server registers the expected tools."""
    from app.mcp.server import create_mcp_server

    mcp = create_mcp_server()

    # The FastMCP instance should have tools registered
    # Tool names we expect
    expected_tools = [
        "ai_complete",
        "ai_list_models",
        "ai_get_usage",
        "job_create",
        "job_list",
        "job_get",
        "job_cancel",
        "billing_get_wallet_balance",
        "billing_list_plans",
        "billing_get_subscription",
        "file_upload",
        "file_download",
        "file_list",
        "team_list_members",
        "team_invite",
    ]

    # Use the public FastMCP API to list registered tools
    registered_tools = await mcp.list_tools()
    registered_names = {t.name for t in registered_tools}

    for name in expected_tools:
        assert name in registered_names, f"Tool '{name}' not registered"
