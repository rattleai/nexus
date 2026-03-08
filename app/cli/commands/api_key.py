"""API key subcommands for the CADPrice CLI."""

from __future__ import annotations

import typer

from app.cli.output import output

api_key_app = typer.Typer(name="api-key", help="API key management")


@api_key_app.command("create")
def create(
    ctx: typer.Context,
    name: str = typer.Option("default", help="Key name"),
    scopes: str | None = typer.Option(None, help="Comma-separated scopes"),
):
    """Create a new API key."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    body: dict = {"name": name}
    if scopes:
        body["scopes"] = [s.strip() for s in scopes.split(",")]

    result = client.post("/api/v1/api-keys", json=body)
    output(result, fmt)


@api_key_app.command("list")
def list_keys(ctx: typer.Context):
    """List API keys."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get("/api/v1/api-keys")
    output(result, fmt, title="API Keys")


@api_key_app.command("revoke")
def revoke(ctx: typer.Context, key_id: str = typer.Argument(help="Key ID to revoke")):
    """Revoke an API key."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.delete(f"/api/v1/api-keys/{key_id}")
    output(result, fmt)
