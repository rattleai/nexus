import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cadprice import __version__
from cadprice.api.middleware import SecurityHeadersMiddleware
from cadprice.api.v1 import v1_router
from cadprice.config import settings

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
SPA_DIR = BASE_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CADPrice %s starting up — debug=%s", __version__, settings.DEBUG)
    yield
    logger.info("CADPrice shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="CADPrice",
        version=__version__,
        description="Manufacturing intelligence platform",
        lifespan=lifespan,
        docs_url="/api_vendors/docs" if settings.DEBUG else None,
        redoc_url="/api_vendors/redoc" if settings.DEBUG else None,
    )

    # Middleware (outermost first)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    )

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
            return JSONResponse({"detail": "Not found"}, status_code=404)
        index = SPA_DIR / "index.html"
        if not index.is_file():
            return JSONResponse({"detail": "Frontend not built"}, status_code=503)
        return FileResponse(str(index))

    return app


app = create_app()
