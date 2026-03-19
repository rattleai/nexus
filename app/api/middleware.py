import hashlib
import hmac
import json
import re
import secrets
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.rate_limit import is_agent_request
from app.config import settings

logger = structlog.stdlib.get_logger()

_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")
_STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths exempt from CSRF protection (API key auth, webhooks, public endpoints)
_CSRF_EXEMPT_PREFIXES = (
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/api/v1/auth/verify-email",
    "/api/v1/auth/accept-invitation",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/oauth/",
    "/api/v1/billing/webhooks",
)

# Paths that serve interactive documentation (Swagger UI / ReDoc).
# These load JS/CSS from cdn.jsdelivr.net and images from fastapi.tiangolo.com,
# so they need a relaxed CSP that still prohibits everything else.
_DOCS_PATHS = frozenset({"/api/docs", "/api/redoc"})


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized request bodies to prevent memory exhaustion.

    File upload endpoints (multipart) use a higher limit configured via
    MAX_UPLOAD_SIZE_BYTES. All other POST/PUT/PATCH requests are capped at
    MAX_REQUEST_BODY_BYTES (default 1 MB).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in {"POST", "PUT", "PATCH"}:
            content_type = request.headers.get("content-type", "")
            is_upload = "multipart/form-data" in content_type
            limit = settings.MAX_UPLOAD_SIZE_BYTES if is_upload else settings.MAX_REQUEST_BODY_BYTES

            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    length = int(content_length)
                except (ValueError, OverflowError):
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "Invalid Content-Length header", "code": "BAD_REQUEST"},
                    )
                if length > limit:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": f"Request body too large (max {limit // 1024} KB)",
                            "code": "PAYLOAD_TOO_LARGE",
                        },
                    )
            elif not is_upload:
                # No Content-Length header (chunked transfer) — require it for
                # non-upload requests to prevent unbounded body reads.
                return JSONResponse(
                    status_code=411,
                    content={"detail": "Content-Length header is required", "code": "LENGTH_REQUIRED"},
                )
        return await call_next(request)


def _add_security_headers(
    response: Response, request_id: str, *, is_agent: bool = False, path: str = "",
) -> None:
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"

    if is_agent:
        # Agents only need request tracing and content-type protection.
        # Skip browser-only headers (CSP, X-Frame-Options, HSTS, etc.)
        # to reduce ~400 bytes of overhead per response.
        return

    response.headers["X-Frame-Options"] = "DENY"
    if not settings.DEBUG:
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains; preload"
        )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), publickey-credentials-get=self"

    if path in _DOCS_PATHS:
        # Swagger UI and ReDoc load assets from cdn.jsdelivr.net and a favicon
        # from fastapi.tiangolo.com.  Allow only those origins, keep everything
        # else locked down.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob: https://fastapi.tiangolo.com; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self'; "
            "worker-src 'self'; "
            "manifest-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self'; "
            "connect-src 'self' wss: ws:; "
            "worker-src 'self'; "
            "manifest-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )


def _generate_csrf_token() -> str:
    """Generate a cryptographic CSRF token."""
    return secrets.token_urlsafe(32)


def _verify_csrf_token(cookie_token: str, header_token: str) -> bool:
    """Verify CSRF token using constant-time comparison (double-submit cookie pattern)."""
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token, header_token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # ── Request ID propagation (validate to prevent log injection) ──
        client_request_id = request.headers.get("X-Request-ID", "")
        if client_request_id and _REQUEST_ID_RE.match(client_request_id):
            request_id = client_request_id
        else:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # ── Agent detection (early, cached on request.state for all downstream) ──
        _is_agent = is_agent_request(request)

        # ── CSRF protection (double-submit cookie pattern, P1-1) ──
        # Only enforce for cookie-based auth on state-changing methods.
        # API key auth (X-API-Key header) and agent requests are inherently CSRF-safe.
        if (
            settings.AUTH_ENABLED
            and not _is_agent
            and request.method in _STATE_CHANGING_METHODS
            and not request.headers.get("X-API-Key")
            and not any(request.url.path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES)
        ):
            # Check if request uses cookie-based auth (has refresh_token cookie)
            if request.cookies.get("refresh_token"):
                csrf_cookie = request.cookies.get("csrf_token", "")
                csrf_header = request.headers.get("X-CSRF-Token", "")
                if not _verify_csrf_token(csrf_cookie, csrf_header):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF token missing or invalid", "code": "CSRF_VALIDATION_FAILED"},
                    )

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

        # Check for idempotency-replayed response (set by IdempotencyGuard dependency).
        # When a cached idempotent response exists, return it instead of the handler's response.
        idempotency_response = getattr(request.state, "idempotency_response", None)
        if idempotency_response is not None:
            response = idempotency_response

        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        # Log every request with timing — warn on server errors
        log_level = "warning" if response.status_code >= 500 else "info"
        getattr(logger, log_level)(
            "request_completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
            client_ip=request.client.host if request.client else "unknown",
        )

        # ── API versioning deprecation headers ──
        if request.url.path.startswith("/api/v1/"):
            response.headers["X-API-Version"] = "v1"
            # When v2 is available, add deprecation notice:
            # response.headers["Deprecation"] = "true"
            # response.headers["Sunset"] = "2027-01-01T00:00:00Z"
            # response.headers["Link"] = '</api/v2/>; rel="successor-version"'

        # ── Security headers & timing ──
        _add_security_headers(response, request_id, is_agent=_is_agent, path=request.url.path)
        response.headers["X-Response-Time"] = f"{duration_ms}ms"

        # ── Rate limit headers on successful responses (P1-12) ──
        rl_limit = getattr(request.state, "rate_limit_limit", None)
        if rl_limit is not None:
            response.headers["X-RateLimit-Limit"] = str(rl_limit)
            response.headers["X-RateLimit-Remaining"] = str(
                getattr(request.state, "rate_limit_remaining", 0)
            )
            response.headers["X-RateLimit-Reset"] = str(
                getattr(request.state, "rate_limit_reset", 0)
            )

        # ── CSRF cookie (only for browser sessions, not agents) ──
        if settings.AUTH_ENABLED and not _is_agent:
            csrf_token = request.cookies.get("csrf_token")
            if not csrf_token:
                csrf_token = _generate_csrf_token()
            response.set_cookie(
                key="csrf_token",
                value=csrf_token,
                httponly=False,  # Must be readable by JavaScript
                secure=not settings.DEBUG,
                samesite="lax",
                path="/",
                max_age=86400,
            )

        return response


# Fields to keep when Prefer: return=minimal is set
_MINIMAL_FIELDS = {"id", "status", "code", "created_at"}

_MUTATION_METHODS = {"POST", "PUT", "PATCH"}


class PreferMinimalMiddleware(BaseHTTPMiddleware):
    """Support RFC 7240 'Prefer: return=minimal' for mutation responses.

    When an agent sends 'Prefer: return=minimal' on a POST/PUT/PATCH request,
    successful responses (2xx with JSON body) are trimmed to only include
    essential fields (id, status, code, created_at), reducing payload size
    significantly for agents that only need confirmation of the operation.

    The response includes 'Preference-Applied: return=minimal' to confirm.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Only apply to mutation methods with minimal preference
        if request.method not in _MUTATION_METHODS:
            return response

        prefer = request.headers.get("Prefer", "")
        if "return=minimal" not in prefer:
            return response

        # Only trim successful JSON responses
        if response.status_code < 200 or response.status_code >= 300:
            return response

        if not hasattr(response, "body"):
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        try:
            body = json.loads(response.body)
        except (json.JSONDecodeError, ValueError):
            return response

        # Trim to minimal fields
        if isinstance(body, dict):
            minimal = {k: v for k, v in body.items() if k in _MINIMAL_FIELDS}
            return JSONResponse(
                status_code=response.status_code,
                content=minimal,
                headers={**dict(response.headers), "Preference-Applied": "return=minimal"},
            )

        # For list responses, trim each item
        if isinstance(body, list):
            minimal = [{k: v for k, v in item.items() if k in _MINIMAL_FIELDS} for item in body if isinstance(item, dict)]
            return JSONResponse(
                status_code=response.status_code,
                content=minimal,
                headers={**dict(response.headers), "Preference-Applied": "return=minimal"},
            )

        return response
