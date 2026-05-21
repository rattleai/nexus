"""Export subcommands for the NEXUS CLI."""

from __future__ import annotations

import time

import typer

from app.cli.output import output

export_app = typer.Typer(name="export", help="GDPR data export operations")


@export_app.command("request")
def request_export(ctx: typer.Context):
    """Request a GDPR data export for the current tenant."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.post("/api/v1/export")
    output(result, fmt)


@export_app.command("status")
def status(ctx: typer.Context, export_id: str = typer.Argument(help="Export ID")):
    """Check the status of an export request."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get(f"/api/v1/export/{export_id}")
    output(result, fmt, title="Export")


@export_app.command("wait")
def wait(
    ctx: typer.Context,
    export_id: str = typer.Argument(help="Export ID"),
    timeout: int = typer.Option(600, help="Max wait time in seconds"),
    interval: int = typer.Option(5, help="Poll interval in seconds"),
):
    """Wait for an export to complete (polls until done or timeout)."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        result = client.get(f"/api/v1/export/{export_id}")
        export_status = result.get("status", "")
        if export_status in ("completed", "failed"):
            output(result, fmt, title="Export")
            if export_status == "failed":
                raise typer.Exit(code=1)
            return
        time.sleep(interval)

    output({"error": f"Timed out after {timeout}s", "export_id": export_id}, fmt)
    raise typer.Exit(code=1)
