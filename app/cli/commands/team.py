"""Team subcommands for the CADPrice CLI."""

from __future__ import annotations

import typer

from app.cli.output import output

team_app = typer.Typer(name="team", help="Team management")


@team_app.command("list")
def list_members(ctx: typer.Context):
    """List team members."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.get("/api/v1/team/members")
    output(result, fmt, title="Team Members")


@team_app.command("invite")
def invite(
    ctx: typer.Context,
    email: str = typer.Option(..., help="Email address to invite"),
    role: str = typer.Option("member", help="Role: member, admin"),
):
    """Invite a user to the team."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output"]

    result = client.post("/api/v1/team/invite", json={"email": email, "role": role})
    output(result, fmt)
