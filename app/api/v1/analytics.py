"""Core Web Vitals analytics endpoint.

Receives performance metrics from the frontend's web-vitals library.
Unauthenticated, fire-and-forget — uses sendBeacon on the client side.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/analytics", tags=["analytics"])


class CWVMetric(BaseModel):
    name: str = Field(..., description="Metric name (LCP, FID, CLS, TTFB, INP)")
    value: float = Field(..., description="Metric value")
    rating: str | None = Field(None, description="good, needs-improvement, or poor")
    delta: float | None = Field(None, description="Delta since last report")
    id: str | None = Field(None, description="Unique metric ID")
    navigationType: str | None = Field(None, description="Navigation type")


@router.post("/cwv", status_code=204)
async def report_cwv(
    metric: CWVMetric,
    request: Request,
) -> None:
    """Receive a Core Web Vitals metric report.

    This endpoint is unauthenticated and rate-limited to 5 req/60s per IP.
    Metrics are logged via structlog and can be forwarded to an analytics backend.
    """
    logger.info(
        "cwv_metric",
        name=metric.name,
        value=metric.value,
        rating=metric.rating,
        delta=metric.delta,
        client_ip=request.client.host if request.client else "unknown",
    )
