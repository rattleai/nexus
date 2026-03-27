"""CPQ application API routes.

Aggregates all CPQ routers into a single router that the plugin
framework includes under ``/api/v1``.
"""

from fastapi import APIRouter

from app.apps.cpq.api.boms import router as boms_router
from app.apps.cpq.api.characteristics import router as characteristics_router
from app.apps.cpq.api.cloud_connections import router as cloud_connections_router
from app.apps.cpq.api.configurator import router as configurator_router
from app.apps.cpq.api.constraints import router as constraints_router
from app.apps.cpq.api.datasources import router as datasources_router
from app.apps.cpq.api.products import router as products_router

router = APIRouter()
router.include_router(products_router, tags=["products"])
router.include_router(characteristics_router, tags=["characteristics"])
router.include_router(constraints_router, tags=["constraints"])
router.include_router(boms_router, tags=["boms"])
router.include_router(configurator_router, tags=["configurator"])
router.include_router(datasources_router, tags=["datasources"])
router.include_router(cloud_connections_router, tags=["cloud-connections"])
