"""File subcommands for the NEXUS CLI."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import typer

from app.cli.output import output

file_app = typer.Typer(name="file", help="File operations")


@file_app.command("upload")
def upload(
    ctx: typer.Context,
    filepath: Path = typer.Argument(help="Path to file to upload"),
    content_type: str | None = typer.Option(None, "--content-type", help="MIME content type"),
):
    """Upload a file to the platform."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    if not filepath.exists():
        typer.echo(f"Error: File not found: {filepath}", err=True)
        raise typer.Exit(code=1)

    if not content_type:
        content_type = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"

    content = filepath.read_bytes()
    content_b64 = base64.b64encode(content).decode()

    result = client.post(
        "/api/v1/files",
        json={
            "filename": filepath.name,
            "content_base64": content_b64,
            "content_type": content_type,
        },
    )
    output(result, fmt)


@file_app.command("download")
def download(
    ctx: typer.Context,
    file_key: str = typer.Argument(help="File key to download"),
    output_path: Path | None = typer.Option(None, "--to", help="Save to file path"),
):
    """Download a file by key."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get(f"/api/v1/files/{file_key}")

    if output_path:
        # Decode base64 content and write to file
        content_b64 = result.get("content_base64", "") if isinstance(result, dict) else ""
        if content_b64:
            output_path.write_bytes(base64.b64decode(content_b64))
        typer.echo(f"Downloaded to {output_path}", err=True)
    else:
        output(result, fmt, title="File")


@file_app.command("list")
def list_files(ctx: typer.Context, prefix: str | None = typer.Option(None, help="Filter by prefix")):
    """List uploaded files."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    params = {}
    if prefix:
        params["prefix"] = prefix

    result = client.get("/api/v1/files", params=params)
    items = result.get("items", result) if isinstance(result, dict) else result
    output(items, fmt, title="Files")
