import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

logger = structlog.stdlib.get_logger()


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized request bodies to prevent memory exhaustion.

    File upload endpoints (multipart) use a higher limit configured via
    MAX_UPLOAD_SIZE_BYTES. All other POST/PUT/PATCH requests are capped at
    MAX_REQUEST_BODY_BYTES (default 1 MB).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length is not None:
                length = int(content_length)
                content_type = request.headers.get("content-type", "")
                is_upload = "multipart/form-data" in content_type
                limit = settings.MAX_UPLOAD_SIZE_BYTES if is_upload else settings.MAX_REQUEST_BODY_BYTES
                if length > limit:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": f"Request body too large (max {limit // 1024} KB)",
                            "code": "PAYLOAD_TOO_LARGE",
                        },
                    )
        return await call_next(request)


def _add_security_headers(response: Response, request_id: str) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if not settings.DEBUG:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["X-Request-ID"] = request_id


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # ── Request ID propagation ──
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # ── Cache bypass detection ──
        cache_control = request.headers.get("Cache-Control", "").lower()
        request.state.cache_bypass = "no-cache" in cache_control

        # Bind request context for all downstream log calls
        structlog.contextvars.clear_contextvars()
        log_ctx: dict = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        }

        # Bind OTEL trace_id if available
        if settings.OTEL_ENABLED:
            try:
                from opentelemetry import trace

                span = trace.get_current_span()
                ctx = span.get_span_context()
                if ctx and ctx.trace_id:
                    log_ctx["trace_id"] = format(ctx.trace_id, "032x")
            except Exception:
                pass

        structlog.contextvars.bind_contextvars(**log_ctx)

        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # Catch unhandled exceptions that escape the exception handlers
            # (BaseHTTPMiddleware can re-raise before FastAPI's handler runs)
            logger.exception("unhandled_exception")
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "code": "INTERNAL_ERROR"},
            )

        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        # Log every request with timing
        logger.info(
            "request_completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        # ── Security headers ──
        _add_security_headers(response, request_id)

        return response
