"""Job subcommands for the NEXUS CLI."""

from __future__ import annotations

import json as json_mod
import time

import typer

from app.cli.output import output

job_app = typer.Typer(name="job", help="Job management")


@job_app.command("create")
def create(
    ctx: typer.Context,
    job_type: str = typer.Option(..., "--type", help="Job type (e.g. export, ai_completion)"),
    payload: str | None = typer.Option(None, help="JSON payload string"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Idempotency key"),
):
    """Create a new background job."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    body = {"type": job_type}
    if payload:
        body["payload"] = json_mod.loads(payload)

    result = client.post("/api/v1/jobs", json=body, idempotency_key=idempotency_key)
    output(result, fmt)


@job_app.command("list")
def list_jobs(
    ctx: typer.Context,
    status: str | None = typer.Option(None, help="Filter by status"),
    limit: int = typer.Option(50, help="Max results"),
):
    """List jobs."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    params = {"limit": limit}
    if status:
        params["status"] = status

    result = client.get("/api/v1/jobs", params=params)
    items = result.get("items", result) if isinstance(result, dict) else result
    output(items, fmt, title="Jobs")


@job_app.command("get")
def get(ctx: typer.Context, job_id: str = typer.Argument(help="Job ID")):
    """Get job details."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get(f"/api/v1/jobs/{job_id}")
    output(result, fmt, title="Job")


@job_app.command("cancel")
def cancel(ctx: typer.Context, job_id: str = typer.Argument(help="Job ID")):
    """Cancel a job."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.post(f"/api/v1/jobs/{job_id}/cancel")
    output(result, fmt)


@job_app.command("wait")
def wait(
    ctx: typer.Context,
    job_id: str = typer.Argument(help="Job ID"),
    timeout: int = typer.Option(300, help="Max wait time in seconds"),
    interval: int = typer.Option(2, help="Poll interval in seconds"),
):
    """Wait for a job to complete (polls until done or timeout)."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        result = client.get(f"/api/v1/jobs/{job_id}")
        status = result.get("status", "")
        if status in ("completed", "failed"):
            output(result, fmt, title="Job")
            if status == "failed":
                raise typer.Exit(code=1)
            return
        time.sleep(interval)

    output({"error": f"Timed out after {timeout}s", "job_id": job_id}, fmt)
    raise typer.Exit(code=1)
