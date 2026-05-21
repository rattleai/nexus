"""CLI entry point — command-line tool for interacting with the platform.

The CLI name, display name, and env var prefix are all configurable
via environment variables for white-labeling. See app.cli.branding.
"""

from __future__ import annotations

import sys

import typer

from app import __version__
from app.cli.branding import API_KEY_ENV, BASE_URL_ENV, CLI_DISPLAY_NAME, CLI_NAME
from app.cli.client import CLIError, NexusClient
from app.cli.commands.ai import ai_app
from app.cli.commands.api_key import api_key_app
from app.cli.commands.billing import billing_app
from app.cli.commands.export import export_app
from app.cli.commands.file import file_app
from app.cli.commands.job import job_app
from app.cli.commands.team import team_app
from app.cli.commands.webhook import webhook_app
from app.cli.output import format_error_json

_VALID_OUTPUT_FORMATS = {"json", "table"}

app = typer.Typer(
    name=CLI_NAME,
    help=f"{CLI_DISPLAY_NAME} CLI — interact with the platform from the command line.",
    no_args_is_help=True,
)

# Register subcommands
app.add_typer(ai_app)
app.add_typer(job_app)
app.add_typer(file_app)
app.add_typer(billing_app)
app.add_typer(team_app)
app.add_typer(api_key_app)
app.add_typer(webhook_app)
app.add_typer(export_app)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"{CLI_NAME} {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        envvar=API_KEY_ENV,
        help="API key for authentication",
    ),
    base_url: str = typer.Option(
        "http://localhost:8000",
        "--base-url",
        envvar=BASE_URL_ENV,
        help="API base URL",
    ),
    output_format: str = typer.Option(
        "table",
        "--output",
        "-o",
        help="Output format: json or table",
    ),
    _version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
):
    """Initialize the CLI context with shared configuration."""
    if output_format not in _VALID_OUTPUT_FORMATS:
        typer.echo(
            f"Error: Invalid output format '{output_format}'. Choose from: {', '.join(sorted(_VALID_OUTPUT_FORMATS))}",
            err=True,
        )
        raise typer.Exit(code=1)

    if not api_key:
        typer.echo(
            f"Error: API key required. Set --api-key or {API_KEY_ENV}.",
            err=True,
        )
        raise typer.Exit(code=1)

    ctx.ensure_object(dict)
    ctx.obj["client"] = NexusClient(base_url=base_url, api_key=api_key)
    ctx.obj["output"] = output_format


def _handle_cli_error(exc: CLIError) -> None:
    """Handle CLI errors with appropriate output."""
    if sys.stdout.isatty():
        typer.echo(f"Error: {exc.message}", err=True)
        if exc.hint:
            typer.echo(f"Hint: {exc.hint}", err=True)
    else:
        typer.echo(format_error_json(exc.message, hint=exc.hint))
    raise typer.Exit(code=exc.exit_code)


# Wrap typer's main to catch CLIError
_original_main = app.__call__


def _wrapped_main(*args, **kwargs):
    try:
        return _original_main(*args, **kwargs)
    except CLIError as exc:
        _handle_cli_error(exc)


app.__call__ = _wrapped_main

if __name__ == "__main__":
    app()
