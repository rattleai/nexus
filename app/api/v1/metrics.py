"""Prometheus metrics endpoint.

Only active when OTEL_ENABLED=true. Exposes metrics in Prometheus text format.
"""

from fastapi import APIRouter, Response

router = APIRouter()


@router.get("/metrics")
async def prometheus_metrics():
    """Expose Prometheus metrics."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
