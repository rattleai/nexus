"""Agent tools contributed by the example plugin.

Tool definitions follow the agent runtime's schema: each tool has a JSON
Schema for inputs and a coroutine handler that receives the parsed
arguments plus tenant + db context.
"""

from __future__ import annotations

from typing import Any

EXAMPLE_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "example_echo": {
        "description": "Echo back the input — useful for verifying agent tool wiring.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Text to echo back."},
            },
            "required": ["message"],
        },
    },
}


async def example_echo(
    message: str,
    *,
    tenant: Any,
    db: Any,
) -> dict[str, Any]:
    """Trivial handler — returns the input verbatim with tenant id attached."""
    return {"tenant_id": str(tenant.id), "echo": message}
