"""Global exception handlers — fail-closed, consistent error responses.

All exceptions are caught and returned as a uniform JSON envelope:
  {"detail": "...", "code": "...", "request_id": "...", "errors": [...], "hint": "..."}

Stack traces are never leaked to clients. They are logged server-side.
When AGENT_HINTS_ENABLED is true, a "hint" field provides actionable guidance for AI agents.
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.api.hints import get_hint
from app.config import settings

logger = structlog.stdlib.get_logger()


def _get_request_id(request: Request) -> str | None:
    """Extract request ID set by SecurityHeadersMiddleware."""
    return getattr(request.state, "request_id", None)


def _maybe_add_hint(content: dict, status_code: int, code: str) -> None:
    """Add an agent-friendly hint to the error response if enabled."""
    if settings.AGENT_HINTS_ENABLED:
        hint = get_hint(status_code, code)
        if hint:
            content["hint"] = hint


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the FastAPI app."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = _get_request_id(request)
        code = f"HTTP_{exc.status_code}"
        content: dict = {
            "detail": exc.detail,
            "code": code,
        }
        if request_id:
            content["request_id"] = request_id
        _maybe_add_hint(content, exc.status_code, code)
        headers = {"X-Request-ID": request_id} if request_id else None
        return JSONResponse(status_code=exc.status_code, content=content, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"])
            errors.append({"field": loc, "message": err["msg"], "type": err["type"]})

        request_id = _get_request_id(request)
        logger.warning("validation_error", errors=errors, request_id=request_id)

        code = "VALIDATION_ERROR"
        content: dict = {
            "detail": "Validation error",
            "code": code,
            "errors": errors,
        }
        if request_id:
            content["request_id"] = request_id
        _maybe_add_hint(content, 422, code)
        headers = {"X-Request-ID": request_id} if request_id else None
        return JSONResponse(status_code=422, content=content, headers=headers)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _get_request_id(request)
        logger.exception("unhandled_exception", exc_type=type(exc).__name__, request_id=request_id)

        code = "INTERNAL_ERROR"
        content: dict = {
            "detail": "Internal server error",
            "code": code,
        }
        if request_id:
            content["request_id"] = request_id
        _maybe_add_hint(content, 500, code)
        headers = {"X-Request-ID": request_id} if request_id else None
        return JSONResponse(status_code=500, content=content, headers=headers)
