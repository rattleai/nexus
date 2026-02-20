import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cadprice import __version__
from cadprice.api.middleware import SecurityHeadersMiddleware
from cadprice.api.v1 import v1_router
from cadprice.config import settings

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["version"] = __version__


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
        docs_url="/api/docs" if settings.DEBUG else None,
        redoc_url="/api/redoc" if settings.DEBUG else None,
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

    # Static files
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    # API routes
    app.include_router(v1_router, prefix=settings.API_V1_PREFIX)

    # Page routes
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse(request, "dashboard/index.html")

    return app


app = create_app()
