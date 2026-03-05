from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.api_keys import router as api_keys_router
from app.api.v1.billing import router as billing_router
from app.api.v1.export import router as export_router
from app.api.v1.files import router as files_router
from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.webhooks import router as webhooks_router
from app.config import settings

v1_router = APIRouter()
v1_router.include_router(health_router, tags=["health"])
v1_router.include_router(tenants_router, tags=["tenants"])
v1_router.include_router(admin_router, tags=["admin"])
v1_router.include_router(api_keys_router, tags=["api-keys"])
v1_router.include_router(jobs_router, tags=["jobs"])
v1_router.include_router(files_router, tags=["files"])
v1_router.include_router(webhooks_router, tags=["webhooks"])
v1_router.include_router(billing_router, tags=["billing"])
v1_router.include_router(export_router, tags=["export"])

if settings.OTEL_ENABLED:
    from app.api.v1.metrics import router as metrics_router

    v1_router.include_router(metrics_router, tags=["metrics"])

if settings.AUTH_ENABLED:
    from app.api.v1.auth_routes import router as auth_router
    from app.api.v1.notifications import router as notifications_router
    from app.api.v1.team import router as team_router

    v1_router.include_router(auth_router, tags=["auth"])
    v1_router.include_router(team_router, tags=["team"])
    v1_router.include_router(notifications_router, tags=["notifications"])
