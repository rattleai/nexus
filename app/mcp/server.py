"""Core MCP server setup.

Registers all tools, resources, and prompts using the MCP SDK's FastMCP class.
Authenticates via API key from environment or initialization parameter.
"""

from __future__ import annotations

import json
import os
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from app.config import settings
from app.mcp.auth import MCPAuthError, authenticate_api_key, check_scopes
from app.mcp.errors import auth_error

logger = structlog.stdlib.get_logger()


def create_mcp_server() -> FastMCP:
    """Create and configure the MCP server with all tools and resources."""
    mcp = FastMCP(
        settings.MCP_SERVER_NAME,
        instructions=(
            "CADPrice MCP Server — a multi-tenant SaaS platform with AI gateway, "
            "job management, billing, file storage, and team management. "
            "Use the available tools to interact with the platform programmatically. "
            "All operations are scoped to the authenticated tenant."
        ),
    )

    # ── Helper: get authenticated tenant context ─────────────

    async def _get_context() -> tuple[Any, Any, Any]:
        """Resolve API key, tenant, and DB session.

        Returns (api_key, tenant, db_session).
        The caller must close the session when done.
        """
        from app.db.session import async_session_factory

        raw_key = os.environ.get("CADPRICE_API_KEY", "")
        if not raw_key:
            raise auth_error("CADPRICE_API_KEY environment variable not set")

        db = async_session_factory()
        try:
            api_key, tenant = await authenticate_api_key(raw_key, db)
            return api_key, tenant, db
        except MCPAuthError as exc:
            await db.close()
            raise auth_error(exc.detail) from exc

    # ── AI Tools ─────────────────────────────────────────────

    @mcp.tool()
    async def ai_complete(
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Run an AI completion with the specified model.

        Provide a model name and messages list. Each message needs 'role' (user/system/assistant)
        and 'content' keys. Returns the completion text and usage stats.

        Example: ai_complete(model="gpt-4o", messages=[{"role": "user", "content": "Hello"}])
        """
        from app.mcp.tools.ai import ai_complete as _ai_complete

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "ai:write")
            result = await _ai_complete(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                tenant=tenant,
                db=db,
            )
            if settings.MCP_LOG_TOOL_CALLS:
                logger.info("mcp_tool_call", tool="ai_complete", tenant_id=str(tenant.id), model=model)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool()
    async def ai_list_models() -> str:
        """List all available AI models with capabilities and availability.

        Returns model IDs, providers, token limits, and feature support.
        Use this before calling ai_complete to check which models are available.
        """
        from app.mcp.tools.ai import ai_list_models as _ai_list_models

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "ai:read")
            result = await _ai_list_models(tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool()
    async def ai_get_usage(days: int = 30) -> str:
        """Get AI usage statistics for the last N days.

        Returns total requests, token counts, cost, and per-model breakdown.
        Defaults to 30 days.
        """
        from app.mcp.tools.ai import ai_get_usage as _ai_get_usage

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "ai:read")
            result = await _ai_get_usage(days=days, tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    # ── Job Tools ────────────────────────────────────────────

    @mcp.tool()
    async def job_create(job_type: str, payload: dict | None = None) -> str:
        """Create a new background job.

        Jobs run asynchronously. Provide a type (e.g. 'export', 'ai_completion')
        and an optional payload dict.
        """
        from app.mcp.tools.jobs import job_create as _job_create

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "jobs:write")
            result = await _job_create(job_type=job_type, payload=payload, tenant=tenant, db=db)
            if settings.MCP_LOG_TOOL_CALLS:
                logger.info("mcp_tool_call", tool="job_create", tenant_id=str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool()
    async def job_list(status: str | None = None, limit: int = 50) -> str:
        """List jobs, optionally filtered by status.

        Valid statuses: pending, processing, completed, failed.
        Returns up to `limit` jobs, newest first.
        """
        from app.mcp.tools.jobs import job_list as _job_list

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "jobs:read")
            result = await _job_list(status=status, limit=limit, tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool()
    async def job_get(job_id: str) -> str:
        """Get full details of a job by its ID.

        Returns status, payload, result, and error information.
        """
        from app.mcp.tools.jobs import job_get as _job_get

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "jobs:read")
            result = await _job_get(job_id=job_id, tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool()
    async def job_cancel(job_id: str) -> str:
        """Cancel a pending or processing job.

        Only jobs that haven't completed can be cancelled.
        """
        from app.mcp.tools.jobs import job_cancel as _job_cancel

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "jobs:write")
            result = await _job_cancel(job_id=job_id, tenant=tenant, db=db)
            if settings.MCP_LOG_TOOL_CALLS:
                logger.info("mcp_tool_call", tool="job_cancel", tenant_id=str(tenant.id), job_id=job_id)
            return json.dumps(result)
        finally:
            await db.close()

    # ── Billing Tools ────────────────────────────────────────

    @mcp.tool()
    async def billing_get_wallet_balance() -> str:
        """Get the current token wallet balance.

        Returns available tokens, lifetime purchased, and consumed.
        Check this before running AI completions to ensure sufficient balance.
        """
        from app.mcp.tools.billing import billing_get_wallet_balance as _get_balance

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "ai:read")
            result = await _get_balance(tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool()
    async def billing_list_plans() -> str:
        """List all available subscription plans with pricing and limits."""
        from app.mcp.tools.billing import billing_list_plans as _list_plans

        api_key, _tenant, db = await _get_context()
        try:
            check_scopes(api_key, "billing:read")
            result = await _list_plans(db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool()
    async def billing_get_subscription() -> str:
        """Get the current subscription details including plan and status."""
        from app.mcp.tools.billing import billing_get_subscription as _get_sub

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "billing:read")
            result = await _get_sub(tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    # ── File Tools ───────────────────────────────────────────

    @mcp.tool()
    async def file_upload(
        filename: str,
        content_base64: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file with base64-encoded content.

        Returns the file key for later retrieval. Content must be base64-encoded.

        Example: file_upload(filename="data.csv", content_base64="SGVsbG8=", content_type="text/csv")
        """
        from app.mcp.tools.files import file_upload as _file_upload

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "files:write")
            result = await _file_upload(
                filename=filename,
                content_base64=content_base64,
                content_type=content_type,
                tenant=tenant,
                db=db,
            )
            if settings.MCP_LOG_TOOL_CALLS:
                logger.info("mcp_tool_call", tool="file_upload", tenant_id=str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool()
    async def file_download(file_key: str) -> str:
        """Download a file by its key. Returns base64-encoded content."""
        from app.mcp.tools.files import file_download as _file_download

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "files:read")
            result = await _file_download(file_key=file_key, tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool()
    async def file_list(prefix: str | None = None) -> str:
        """List uploaded files, optionally filtered by prefix."""
        from app.mcp.tools.files import file_list as _file_list

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "files:read")
            result = await _file_list(prefix=prefix, tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    # ── Team Tools ───────────────────────────────────────────

    @mcp.tool()
    async def team_list_members() -> str:
        """List all members of the current team with roles and emails."""
        from app.mcp.tools.team import team_list_members as _list_members

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "team:read")
            result = await _list_members(tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool()
    async def team_invite(email: str, role: str = "member") -> str:
        """Invite a user to the team by email.

        Creates a pending invitation. Valid roles: member, admin.
        """
        from app.mcp.tools.team import team_invite as _team_invite

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "team:write")
            result = await _team_invite(email=email, role=role, tenant=tenant, db=db)
            if settings.MCP_LOG_TOOL_CALLS:
                logger.info("mcp_tool_call", tool="team_invite", tenant_id=str(tenant.id), email=email)
            return json.dumps(result)
        finally:
            await db.close()

    # ── Resources ────────────────────────────────────────────

    @mcp.resource("cadprice://models")
    async def resource_models() -> str:
        """Available AI models and their capabilities."""
        from app.mcp.tools.ai import ai_list_models as _ai_list_models

        _api_key, tenant, db = await _get_context()
        try:
            result = await _ai_list_models(tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.resource("cadprice://wallet/balance")
    async def resource_wallet_balance() -> str:
        """Current token wallet balance."""
        from app.mcp.tools.billing import billing_get_wallet_balance as _get_balance

        _api_key, tenant, db = await _get_context()
        try:
            result = await _get_balance(tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    # ── Prompts ──────────────────────────────────────────────

    @mcp.prompt()
    async def list_available_prompts() -> str:
        """List the tenant's saved prompt templates for AI completions."""
        from sqlalchemy import select

        from app.db.models.ai import PromptTemplate

        _api_key, tenant, db = await _get_context()
        try:
            result = await db.execute(
                select(PromptTemplate)
                .where(
                    PromptTemplate.tenant_id == tenant.id,
                    PromptTemplate.deleted_at.is_(None),
                )
                .order_by(PromptTemplate.created_at.desc())
            )
            templates = result.scalars().all()
            items = [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "description": t.description,
                    "system_prompt": t.system_prompt,
                    "variables": t.variables,
                }
                for t in templates
            ]
            return json.dumps(items)
        finally:
            await db.close()

    return mcp
