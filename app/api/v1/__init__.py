from fastapi import APIRouter

from app.api.v1.api_keys import router as api_keys_router
from app.api.v1.files import router as files_router
from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.tenants import router as tenants_router

v1_router = APIRouter()
v1_router.include_router(health_router, tags=["health"])
v1_router.include_router(tenants_router, tags=["tenants"])
v1_router.include_router(api_keys_router, tags=["api-keys"])
v1_router.include_router(jobs_router, tags=["jobs"])
v1_router.include_router(files_router, tags=["files"])
