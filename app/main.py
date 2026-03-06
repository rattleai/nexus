from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import app.core.event_handlers as _event_handlers  # noqa: F401 — registers handlers on import
from app import __version__
from app.api.exceptions import register_exception_handlers
from app.api.middleware import RequestSizeLimitMiddleware, SecurityHeadersMiddleware
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

    logger.info("app_starting", version=__version__, debug=settings.DEBUG)

    # Warm up Redis connection pool
    try:
        await redis_pool.ping()
        logger.info("redis_connected")
    except Exception:
        logger.warning("redis_unavailable_at_startup")

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
        docs_url="/api/docs" if settings.DEBUG else None,
        redoc_url="/api/redoc" if settings.DEBUG else None,
    )

    # Exception handlers (fail-closed)
    register_exception_handlers(app)

    # Middleware — Starlette executes in reverse order of registration:
    # last added = outermost. We want:
    #   CORS (outermost) → SecurityHeaders → RequestSizeLimit → GZip (innermost)
    # So size limit checks Content-Length BEFORE gzip decompresses the body,
    # preventing gzip bombs from exhausting memory.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Admin-Key", "X-Request-ID"],
        max_age=86400,
    )

    # OpenTelemetry (must be before routes so instrumentation hooks are in place)
    if settings.OTEL_ENABLED:
        from app.core.telemetry import setup_telemetry

        setup_telemetry(settings.OTEL_SERVICE_NAME)

    # API routes (must be before SPA catch-all)
    app.include_router(v1_router, prefix=settings.API_V1_PREFIX)

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
