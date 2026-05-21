"""Structured JSON logging configuration using structlog.

Provides:
- JSON output in production, human-readable coloured output in dev
- Automatic request_id, tenant_id propagation via contextvars
- stdlib logging integration so third-party libraries also emit structured logs
- Compact tracebacks that filter out framework internals
"""

import logging
import os
import sys
import traceback
from typing import Any

import structlog

from app.config import settings

# Prefixes considered "app code" — everything else is framework noise.
_APP_PATH_PREFIX = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # …/app


def _is_app_frame(filename: str) -> bool:
    """Return True if filename belongs to the application (not a library)."""
    return filename.startswith(_APP_PATH_PREFIX)


def compact_traceback(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Replace verbose tracebacks with compact, app-only versions.

    Framework frames (uvicorn, starlette, fastapi, asyncio, sqlalchemy, …) are
    collapsed into a single "... N framework frames ..." line so the developer
    can focus on their own code.
    """
    exc_info = event_dict.get("exc_info")
    if not exc_info:
        return event_dict

    # structlog may pass True (meaning "grab from sys.exc_info") or a tuple.
    if exc_info is True:
        exc_info = sys.exc_info()
    if not isinstance(exc_info, tuple) or exc_info[2] is None:
        return event_dict

    exc_type, exc_value, exc_tb = exc_info
    frames = traceback.extract_tb(exc_tb)

    # Always keep the very last frame — it's where the exception was raised,
    # even if it lives in a library (e.g. SQLAlchemy integrity error).
    last_frame_idx = len(frames) - 1

    compact_lines: list[str] = []
    skipped = 0

    def _format_frame(frame: traceback.FrameSummary) -> None:
        rel = os.path.relpath(frame.filename, _APP_PATH_PREFIX)
        # If relpath escapes the app tree it will start with ".."
        path = f"app/{rel}" if not rel.startswith("..") else frame.filename
        compact_lines.append(f"  File {path}:{frame.lineno} in {frame.name}")
        if frame.line:
            compact_lines.append(f"    {frame.line}")

    for idx, frame in enumerate(frames):
        is_last = idx == last_frame_idx
        if _is_app_frame(frame.filename) or is_last:
            if skipped:
                compact_lines.append(f"  ... {skipped} framework frame{'s' if skipped != 1 else ''} ...")
                skipped = 0
            _format_frame(frame)
        else:
            skipped += 1

    if skipped:
        compact_lines.append(f"  ... {skipped} framework frame{'s' if skipped != 1 else ''} ...")

    # Exception line
    exc_str = traceback.format_exception_only(exc_type, exc_value)
    compact_lines.append("".join(exc_str).rstrip())

    # Replace exc_info with a pre-formatted string so downstream processors
    # (ConsoleRenderer / JSONRenderer) render it directly.
    event_dict.pop("exc_info", None)
    event_dict["traceback"] = "\n".join(compact_lines)

    return event_dict


def _add_otel_context(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Inject OpenTelemetry trace_id and span_id into log entries."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except Exception:
        pass
    return event_dict


def setup_logging() -> None:
    """Configure structlog + stdlib logging. Call once at app startup."""

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.OTEL_ENABLED:
        shared_processors.append(_add_otel_context)

    # Compact tracebacks: collapse framework frames, keep only app code.
    shared_processors.append(compact_traceback)

    if settings.DEBUG:
        # Pretty console output for local development
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        # JSON for production (machine-parseable for Loki/ELK/Datadog)
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
