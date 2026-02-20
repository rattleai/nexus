from fastapi import APIRouter

from cadprice.api.v1.health import router as health_router
from cadprice.api.v1.pages import router as pages_router

v1_router = APIRouter()
v1_router.include_router(health_router, tags=["health"])
v1_router.include_router(pages_router, tags=["pages"])
