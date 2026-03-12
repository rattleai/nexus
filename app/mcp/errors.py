"""Map platform exceptions to MCP JSON-RPC error codes."""

from __future__ import annotations

from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

# Standard JSON-RPC error codes
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Custom domain error codes (in the -32000 to -32099 range)
AUTH_ERROR = -32001
INSUFFICIENT_BALANCE = -32002
QUOTA_EXCEEDED = -32003
NOT_FOUND = -32004
CONFLICT = -32005
PROVIDER_ERROR = -32006


def tool_error(message: str, *, hint: str | None = None, code: int = INVALID_PARAMS) -> McpError:
    """Create an McpError with an optional hint for agents."""
    detail = message
    if hint:
        detail = f"{message} | Hint: {hint}"
    return McpError(ErrorData(code=code, message=detail))


def auth_error(detail: str = "Authentication failed") -> McpError:
    return tool_error(
        detail,
        hint="Ensure the MCP server was started with a valid CADPRICE_API_KEY environment variable.",
    )


def not_found_error(resource: str) -> McpError:
    return tool_error(f"{resource} not found")


def insufficient_balance_error(available: int = 0) -> McpError:
    return tool_error(
        f"Insufficient wallet balance (available: {available} tokens)",
        hint="Top up the wallet using the billing_topup_wallet tool or POST /api/v1/ai/wallet/topup.",
    )
