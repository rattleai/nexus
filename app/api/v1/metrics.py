"""Prometheus metrics endpoint.

Only active when OTEL_ENABLED=true. Exposes metrics in Prometheus text format.
Requires admin key to prevent leaking internal metrics to unauthenticated callers.
"""

from fastapi import APIRouter, Depends, Response

from app.api.deps import require_admin_key

router = APIRouter()


@router.get("/metrics", dependencies=[Depends(require_admin_key)])
async def prometheus_metrics():
    """Expose Prometheus metrics. Requires X-Admin-Key header."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
