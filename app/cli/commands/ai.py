"""AI subcommands for the CADPrice CLI."""

from __future__ import annotations

import typer

from app.cli.output import output

ai_app = typer.Typer(name="ai", help="AI gateway operations")


@ai_app.command("complete")
def complete(
    ctx: typer.Context,
    model: str = typer.Option(..., help="Model name (e.g. gpt-4o)"),
    message: str = typer.Option(..., help="User message content"),
    max_tokens: int | None = typer.Option(None, help="Maximum tokens to generate"),
    temperature: float | None = typer.Option(None, help="Temperature (0.0-2.0)"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Idempotency key for safe retries"),
):
    """Run an AI completion."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    body = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if temperature is not None:
        body["temperature"] = temperature

    result = client.post("/api/v1/ai/completions", json=body, idempotency_key=idempotency_key)
    output(result, fmt)


@ai_app.command("models")
def models(ctx: typer.Context):
    """List available AI models."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get("/api/v1/ai/models")
    output(result, fmt, title="AI Models")


@ai_app.command("usage")
def usage(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to report"),
):
    """Show AI usage statistics."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get("/api/v1/ai/usage", params={"days": days})
    output(result, fmt, title="AI Usage")


@ai_app.command("wallet")
def wallet(ctx: typer.Context):
    """Show wallet balance."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get("/api/v1/ai/wallet/balance")
    output(result, fmt, title="Wallet Balance")
