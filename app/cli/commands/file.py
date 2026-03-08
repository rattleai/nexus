"""File subcommands for the CADPrice CLI."""

from __future__ import annotations

from pathlib import Path

import typer

from app.cli.output import output

file_app = typer.Typer(name="file", help="File operations")


@file_app.command("upload")
def upload(
    ctx: typer.Context,
    filepath: Path = typer.Argument(help="Path to file to upload"),
):
    """Upload a file."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    if not filepath.exists():
        typer.echo(f"File not found: {filepath}", err=True)
        raise typer.Exit(code=1)

    content = filepath.read_bytes()
    import mimetypes

    content_type = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"

    # Use multipart upload via the REST API
    import httpx

    response = httpx.post(
        f"{client.base_url}/api/v1/files",
        headers={
            "X-API-Key": client.api_key,
            "User-Agent": client._client.headers.get("User-Agent", "cadprice-cli"),
        },
        files={"file": (filepath.name, content, content_type)},
    )

    if response.status_code >= 400:
        typer.echo(f"Upload failed: {response.text}", err=True)
        raise typer.Exit(code=1)

    output(response.json(), fmt)


@file_app.command("download")
def download(
    ctx: typer.Context,
    file_key: str = typer.Argument(help="File key to download"),
    output_path: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Download a file by key."""
    client = ctx.obj["client"]

    result = client.get(f"/api/v1/files/{file_key}")

    if output_path:
        if isinstance(result, bytes):
            data = result
        elif isinstance(result, str):
            data = result.encode()
        else:
            data = b""
        output_path.write_bytes(data)
        typer.echo(f"Downloaded to {output_path}")
    else:
        typer.echo(f"File key: {file_key}")
