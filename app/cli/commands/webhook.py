"""Webhook subcommands for the CADPrice CLI."""

from __future__ import annotations

import typer

from app.cli.output import output

webhook_app = typer.Typer(name="webhook", help="Webhook endpoint management")


@webhook_app.command("list")
def list_webhooks(ctx: typer.Context):
    """List all configured webhook endpoints."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get("/api/v1/webhooks")
    items = result.get("items", result) if isinstance(result, dict) else result
    output(items, fmt, title="Webhooks")


@webhook_app.command("create")
def create(
    ctx: typer.Context,
    url: str = typer.Option(..., help="Webhook URL (must be HTTPS)"),
    events: list[str] = typer.Option(..., "--event", help="Events to subscribe to"),
    description: str | None = typer.Option(None, help="Description"),
):
    """Create a webhook endpoint."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    body = {"url": url, "events": events}
    if description:
        body["description"] = description

    result = client.post("/api/v1/webhooks", json=body)
    output(result, fmt)


@webhook_app.command("delete")
def delete(ctx: typer.Context, webhook_id: str = typer.Argument(help="Webhook ID")):
    """Delete a webhook endpoint."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.delete(f"/api/v1/webhooks/{webhook_id}")
    output(result, fmt)


@webhook_app.command("events")
def events(ctx: typer.Context):
    """List available webhook event types."""
    from app.api.v1.webhooks import VALID_WEBHOOK_EVENTS

    fmt = ctx.obj["output"]
    output([{"event": e} for e in VALID_WEBHOOK_EVENTS], fmt, title="Webhook Events")
