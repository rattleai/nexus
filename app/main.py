from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import app.core.event_handlers as _event_handlers  # noqa: F401 — registers handlers on import
from app import __version__
from app.api.etag import ETagMiddleware
from app.api.exceptions import register_exception_handlers
from app.api.middleware import PreferMinimalMiddleware, RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from app.api.v1 import v1_router
from app.config import settings, validate_settings
from app.core.logging import setup_logging
from app.core.redis import redis_pool

setup_logging()
logger = structlog.stdlib.get_logger()

BASE_DIR = Path(__file__).resolve().parent.parent
SPA_DIR = BASE_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate configuration before anything else
    validate_settings()

    # Register sync change tracking hooks for ChangeLog population
    from app.db.sync_hooks import register_sync_hooks

    register_sync_hooks()

    # Enable DB connection pool monitoring (P0-8)
    from app.db.session import setup_pool_monitoring
    setup_pool_monitoring()

    logger.info("app_starting", version=__version__, debug=settings.DEBUG)

    # Warm up Redis connection pool
    try:
        await redis_pool.ping()
        logger.info("redis_connected")
    except Exception:
        logger.warning("redis_unavailable_at_startup")

    # Verify the DB connection role is NOT a superuser (superusers bypass RLS)
    from sqlalchemy import text as sa_text

    from app.db.session import async_engine

    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(sa_text("SELECT current_user, usesuper FROM pg_user WHERE usename = current_user"))
            row = result.one_or_none()
            if row and row[1]:
                logger.error(
                    "rls_bypass_risk",
                    db_user=row[0],
                    detail="Connected as superuser — Row-Level Security policies will NOT be enforced. "
                    "Use a non-superuser role (e.g. app_user) in production.",
                )
                if not settings.DEBUG:
                    raise RuntimeError(
                        f"Database user '{row[0]}' is a superuser, which bypasses RLS. "
                        "Configure DATABASE_URL to use a non-superuser role."
                    )
            else:
                logger.info("rls_verified", db_user=row[0] if row else "unknown")
    except RuntimeError:
        raise
    except Exception:
        logger.warning("rls_check_skipped", exc_info=True)

    yield

    # Graceful shutdown — dispose resources in reverse init order with timeouts
    import asyncio

    logger.info("app_shutting_down")

    if settings.OTEL_ENABLED:
        from app.core.telemetry import shutdown_telemetry

        shutdown_telemetry()

    # Close Redis (with timeout to prevent hanging during deployment)
    try:
        await asyncio.wait_for(redis_pool.aclose(), timeout=5.0)
    except TimeoutError:
        logger.warning("redis_close_timeout")
    except Exception:
        logger.warning("redis_close_error", exc_info=True)

    # Dispose database engines to release connection pools
    from app.db.session import dispose_engines

    try:
        await asyncio.wait_for(dispose_engines(), timeout=10.0)
    except TimeoutError:
        logger.warning("db_engine_dispose_timeout")

    logger.info("app_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SaaS Platform",
        version=__version__,
        description="Multi-tenant SaaS platform",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # Exception handlers (fail-closed)
    register_exception_handlers(app)

    # Middleware — Starlette executes in reverse order of registration:
    # last added = outermost. We want:
    #   CORS (outermost) → SecurityHeaders → RequestSizeLimit → ETag → GZip (innermost)
    # ETag is inside GZip so it computes on uncompressed body.
    # Size limit checks Content-Length BEFORE gzip decompresses the body,
    # preventing gzip bombs from exhausting memory.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(ETagMiddleware)
    app.add_middleware(PreferMinimalMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization", "Content-Type", "X-API-Key", "X-Admin-Key",
            "X-Request-ID", "X-Idempotency-Key", "If-None-Match", "X-CSRF-Token",
            "X-Agent-Name", "Prefer",
        ],
        expose_headers=[
            "ETag", "X-Request-ID", "X-Response-Time", "Retry-After",
            "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset",
            "X-CSRF-Token", "X-Agent-Name", "Preference-Applied",
        ],
        max_age=86400,
    )

    # OpenTelemetry (must be before routes so instrumentation hooks are in place)
    if settings.OTEL_ENABLED:
        from app.core.telemetry import setup_telemetry

        setup_telemetry(settings.OTEL_SERVICE_NAME)

    # ── Plugin Discovery Endpoints ─────────────────────────────
    # These endpoints enable the platform to be consumed as a plugin
    # by Claude, OpenAI, Microsoft Copilot, Langdock, Gemini, and others.

    @app.get("/.well-known/ai-plugin.json")
    async def ai_plugin_manifest():
        """OpenAI GPT Actions / Microsoft Copilot plugin manifest."""
        return {
            "schema_version": "v1",
            "name_for_human": "CADPrice",
            "name_for_model": "cadprice",
            "description_for_human": "Multi-tenant SaaS platform with AI gateway, agent orchestration, billing, and file management.",
            "description_for_model": "Use CADPrice to run AI completions via a multi-provider gateway, manage and execute AI agents, create background jobs, upload/download files, track billing and usage, and manage team members and webhooks. All operations are scoped to the authenticated tenant.",
            "auth": {
                "type": "service_http",
                "authorization_type": "bearer",
                "verification_tokens": {},
            },
            "api": {
                "type": "openapi",
                "url": f"{settings.APP_BASE_URL}/api/v1/openapi.json",
            },
            "logo_url": f"{settings.APP_BASE_URL}/logo.png",
            "contact_email": "support@cadprice.com",
            "legal_info_url": f"{settings.APP_BASE_URL}/legal/privacy",
        }

    @app.get("/legal/privacy")
    async def privacy_policy():
        """Privacy policy endpoint (required for GPT Store and plugin publishing)."""
        from starlette.responses import HTMLResponse
        return HTMLResponse(
            "<html><head><title>CADPrice Privacy Policy</title></head><body>"
            "<h1>Privacy Policy</h1>"
            "<p>CADPrice processes data on behalf of authenticated tenants. "
            "All data is tenant-scoped via row-level security. "
            "We implement GDPR Article 25 (privacy by design) with consent tracking, "
            "data subject access request handling, and configurable retention policies.</p>"
            "<p>For data requests, contact: privacy@cadprice.com</p>"
            "</body></html>"
        )

    # MCP .well-known discovery endpoint (Nov 2025 spec)
    @app.get("/.well-known/mcp")
    async def mcp_discovery():
        """MCP server capability discovery per the November 2025 spec."""
        return {
            "name": settings.MCP_SERVER_NAME,
            "version": __version__,
            "description": "CADPrice multi-tenant SaaS platform MCP server",
            "transport": settings.MCP_TRANSPORT,
            "url": f"{settings.APP_BASE_URL}/mcp" if settings.MCP_TRANSPORT == "http" else None,
            "api_bridge": f"{settings.APP_BASE_URL}/mcp" if settings.MCP_EXPOSE_API_ROUTES else None,
            "authentication": {"type": "api_key", "header": "X-API-Key"},
            "capabilities": {
                "tools": True,
                "resources": True,
                "prompts": True,
                "streaming": True,
            },
            "tool_annotations": {
                "ai_complete": {"readOnly": False, "costImplication": "high"},
                "ai_list_models": {"readOnly": True, "costImplication": "none"},
                "file_upload": {"readOnly": False, "costImplication": "low"},
                "file_list": {"readOnly": True, "costImplication": "none"},
                "job_create": {"readOnly": False, "costImplication": "medium"},
                "job_list": {"readOnly": True, "costImplication": "none"},
                "webhook_create": {"readOnly": False, "costImplication": "none"},
                "code_execute": {"readOnly": False, "costImplication": "low"},
                "agent_list": {"readOnly": True, "costImplication": "none"},
                "agent_run": {"readOnly": False, "costImplication": "high"},
                "agent_approve": {"readOnly": False, "costImplication": "none"},
            },
        }

    # API routes (must be before SPA catch-all)
    app.include_router(v1_router, prefix=settings.API_V1_PREFIX)

    # Mount fastapi-mcp bridge (auto-exposes API routes as MCP tools)
    from app.mcp.api_bridge import mount_api_mcp

    mount_api_mcp(app)

    # Enrich OpenAPI schema with agent-friendly metadata
    _original_openapi = app.openapi

    def _enriched_openapi():
        schema = _original_openapi()
        from app.api.openapi_enrichment import enrich_openapi_schema
        return enrich_openapi_schema(schema)

    app.openapi = _enriched_openapi

    # ── Two-Tier OpenAPI: public (filtered) vs admin (full) ───────
    from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html

    from app.api.deps import require_admin_key
    from app.api.openapi_enrichment import filter_internal_paths

    @app.get("/api/v1/openapi.json", include_in_schema=False)
    async def public_openapi():
        """Public OpenAPI spec with internal paths stripped."""
        return JSONResponse(filter_internal_paths(app.openapi()))

    @app.get("/admin/openapi.json", include_in_schema=False, dependencies=[Depends(require_admin_key)])
    async def admin_openapi():
        """Full unfiltered OpenAPI spec — admin only."""
        return JSONResponse(app.openapi())

    if settings.DEBUG:
        @app.get("/api/docs", include_in_schema=False)
        async def swagger_ui():
            return get_swagger_ui_html(
                openapi_url="/api/v1/openapi.json",
                title=f"{app.title} — Swagger UI",
            )

        @app.get("/api/redoc", include_in_schema=False)
        async def redoc_ui():
            return get_redoc_html(
                openapi_url="/api/v1/openapi.json",
                title=f"{app.title} — ReDoc",
            )

    # SPA static assets
    if (SPA_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(SPA_DIR / "assets")), name="assets")

    # SPA catch-all — serves index.html for all non-API routes
    api_root = settings.API_V1_PREFIX.strip("/").split("/")[0]  # e.g. "api" from "api/v1"

    @app.get("/{full_path:path}")
    async def spa_catch_all(request: Request, full_path: str):
        if full_path == api_root or full_path.startswith(api_root + "/"):
            return JSONResponse({"detail": "Not found", "code": "HTTP_404"}, status_code=404)
        index = SPA_DIR / "index.html"
        if not index.is_file():
            return JSONResponse({"detail": "Frontend not built", "code": "SERVICE_UNAVAILABLE"}, status_code=503)
        return FileResponse(str(index))

    return app


app = create_app()
