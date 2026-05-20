"""Entry point for the NEXUS MCP server.

Run via: nxs-mcp
Or: python -m app.mcp.run

Supports two transports:
- stdio (default for local agent connections)
- http (for remote agent connections)

Configure via environment variables:
- MCP_TRANSPORT: "stdio" or "http" (default: from settings)
- MCP_HTTP_PORT: Port for HTTP transport (default: 8001)
- NXS_API_KEY: API key for authenticating the MCP session
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Start the MCP server with the configured transport."""
    from app.config import settings
    from app.mcp.server import create_mcp_server

    if not settings.MCP_ENABLED:
        print("MCP server is disabled. Set MCP_ENABLED=true to enable.", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("NXS_API_KEY"):
        print("NXS_API_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)

    mcp = create_mcp_server()

    transport = os.environ.get("MCP_TRANSPORT", settings.MCP_TRANSPORT)
    # Backward compat: accept legacy transport name
    if transport == "streamable-http":
        transport = "http"
    port = int(os.environ.get("MCP_HTTP_PORT", str(settings.MCP_HTTP_PORT)))

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
