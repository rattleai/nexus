"""Output formatting for the CLI.

Supports two modes:
- json: Raw JSON output (for agents and piping)
- table: Human-readable table output (for interactive use)
"""

from __future__ import annotations

import json
import sys
from typing import Any


def format_json(data: Any) -> str:
    """Format data as pretty JSON."""
    return json.dumps({"status": "ok", "data": data}, indent=2, default=str)


def format_error_json(message: str, code: str = "ERROR", hint: str | None = None) -> str:
    """Format an error as JSON."""
    result: dict[str, Any] = {"status": "error", "code": code, "detail": message}
    if hint:
        result["hint"] = hint
    return json.dumps(result, indent=2)


def format_table(data: list[dict] | dict, title: str | None = None) -> str:
    """Format data as a human-readable table.

    Uses simple text formatting. If rich is available, uses rich tables.
    """
    if isinstance(data, dict):
        # Single record — format as key-value pairs
        lines = []
        if title:
            lines.append(f"── {title} ──")
        max_key_len = max(len(k) for k in data) if data else 0
        for key, value in data.items():
            lines.append(f"  {key:<{max_key_len}}  {value}")
        return "\n".join(lines)

    if not data:
        return "No results."

    # List of records — format as table
    headers = list(data[0].keys())
    col_widths = {h: len(h) for h in headers}
    for row in data:
        for h in headers:
            val = str(row.get(h, ""))
            col_widths[h] = max(col_widths[h], min(len(val), 40))

    lines = []
    if title:
        lines.append(f"── {title} ──")

    # Header row
    header_line = "  ".join(h.ljust(col_widths[h]) for h in headers)
    lines.append(header_line)
    lines.append("  ".join("─" * col_widths[h] for h in headers))

    # Data rows
    for row in data:
        vals = []
        for h in headers:
            val = str(row.get(h, ""))
            if len(val) > 40:
                val = val[:37] + "..."
            vals.append(val.ljust(col_widths[h]))
        lines.append("  ".join(vals))

    return "\n".join(lines)


def output(data: Any, output_format: str = "table", title: str | None = None) -> None:
    """Write formatted output to stdout."""
    if output_format == "json":
        sys.stdout.write(format_json(data) + "\n")
    elif not sys.stdout.isatty():
        # Non-TTY: fall back to JSON for machine consumption
        sys.stdout.write(format_json(data) + "\n")
    else:
        sys.stdout.write(format_table(data, title=title) + "\n")
