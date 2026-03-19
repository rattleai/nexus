"""Health check endpoints — Kubernetes liveness and readiness probes."""

from fastapi import APIRouter

from app import __version__

router = APIRouter(prefix="/health")


@router.get("/live")
async def liveness():
    """Liveness probe — returns 200 if the process is running."""
    return {"status": "ok", "version": __version__}


@router.get("/ready")
async def readiness():
    """Readiness probe — checks downstream dependencies."""
    checks: dict[str, str] = {}
    overall = "ok"

    # Add dependency checks here (DB, Redis, etc.)

    return {"status": overall, "version": __version__, "checks": checks}
