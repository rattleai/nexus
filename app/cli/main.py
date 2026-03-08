"""CADPrice CLI — command-line tool for interacting with the CADPrice platform.

Usage:
    cadprice [OPTIONS] COMMAND [ARGS]...

Global options:
    --api-key TEXT      API key (or set CADPRICE_API_KEY env var)
    --base-url TEXT     API base URL (or set CADPRICE_BASE_URL env var)
    --output TEXT       Output format: json or table (default: table)

Examples:
    cadprice ai models --output json
    cadprice job list --status pending
    cadprice ai complete --model gpt-4o --message "Hello"
    cadprice billing wallet
"""

from __future__ import annotations

import sys

import typer

from app.cli.client import CadpriceClient, CLIError
from app.cli.commands.ai import ai_app
from app.cli.commands.api_key import api_key_app
from app.cli.commands.billing import billing_app
from app.cli.commands.file import file_app
from app.cli.commands.job import job_app
from app.cli.commands.team import team_app
from app.cli.output import format_error_json

app = typer.Typer(
    name="cadprice",
    help="CADPrice CLI — interact with the CADPrice platform from the command line.",
    no_args_is_help=True,
)

# Register subcommands
app.add_typer(ai_app)
app.add_typer(job_app)
app.add_typer(file_app)
app.add_typer(billing_app)
app.add_typer(team_app)
app.add_typer(api_key_app)


@app.callback()
def main(
    ctx: typer.Context,
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        envvar="CADPRICE_API_KEY",
        help="API key for authentication",
    ),
    base_url: str = typer.Option(
        "http://localhost:8000",
        "--base-url",
        envvar="CADPRICE_BASE_URL",
        help="CADPrice API base URL",
    ),
    output_format: str = typer.Option(
        "table",
        "--output",
        "-o",
        help="Output format: json or table",
    ),
):
    """Initialize the CLI context with shared configuration."""
    if not api_key:
        typer.echo("Error: API key required. Set --api-key or CADPRICE_API_KEY.", err=True)
        raise typer.Exit(code=1)

    ctx.ensure_object(dict)
    ctx.obj["client"] = CadpriceClient(base_url=base_url, api_key=api_key)
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
