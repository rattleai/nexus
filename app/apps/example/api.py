"""HTTP routes contributed by the example plugin.

Mounted under ``/api/v1`` by the plugin registry. Demonstrates the minimum
shape of a plugin-owned router: a tag for OpenAPI grouping, a single
endpoint, a dependency on the platform's tenant resolution.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_tenant
from app.db.models.core import Tenant

router = APIRouter(prefix="/example", tags=["example"])


@router.get("/ping", summary="Plugin health probe")
async def ping(tenant: Tenant = Depends(get_current_tenant)) -> dict[str, str]:
    """Return a tenant-scoped pong payload.

    Verifies that:
    - the plugin's router was discovered and mounted,
    - tenant resolution works inside plugin code,
    - the plugin can read the platform's models.
    """
    return {"plugin": "example", "tenant_id": str(tenant.id), "message": "pong"}
