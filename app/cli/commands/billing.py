"""Billing subcommands for the CADPrice CLI."""

from __future__ import annotations

import typer

from app.cli.output import output

billing_app = typer.Typer(name="billing", help="Billing and subscription management")


@billing_app.command("plans")
def plans(ctx: typer.Context):
    """List available subscription plans."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get("/api/v1/billing/plans")
    output(result, fmt, title="Plans")


@billing_app.command("subscription")
def subscription(ctx: typer.Context):
    """Show current subscription details."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get("/api/v1/billing/subscription")
    output(result, fmt, title="Subscription")


@billing_app.command("wallet")
def wallet(ctx: typer.Context):
    """Show wallet balance."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get("/api/v1/ai/wallet/balance")
    output(result, fmt, title="Wallet Balance")
