"""Global exception handlers — fail-closed, consistent error responses.

All exceptions are caught and returned as a uniform JSON envelope:
  {"detail": "...", "code": "...", "request_id": "...", "errors": [...]}

Stack traces are never leaked to clients. They are logged server-side.
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

logger = structlog.stdlib.get_logger()


def _get_request_id(request: Request) -> str | None:
    """Extract request ID set by SecurityHeadersMiddleware."""
    return getattr(request.state, "request_id", None)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the FastAPI app."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = _get_request_id(request)
        content: dict = {
            "detail": exc.detail,
            "code": f"HTTP_{exc.status_code}",
        }
        if request_id:
            content["request_id"] = request_id
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

        content: dict = {
            "detail": "Validation error",
            "code": "VALIDATION_ERROR",
            "errors": errors,
        }
        if request_id:
            content["request_id"] = request_id
        headers = {"X-Request-ID": request_id} if request_id else None
        return JSONResponse(status_code=422, content=content, headers=headers)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _get_request_id(request)
        logger.exception("unhandled_exception", exc_type=type(exc).__name__, request_id=request_id)

        content: dict = {
            "detail": "Internal server error",
            "code": "INTERNAL_ERROR",
        }
        if request_id:
            content["request_id"] = request_id
        headers = {"X-Request-ID": request_id} if request_id else None
        return JSONResponse(status_code=500, content=content, headers=headers)
