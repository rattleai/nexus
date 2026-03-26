"""Core MCP server setup.

Registers all tools, resources, and prompts using the FastMCP framework.
Authenticates via API key from environment or initialization parameter.
"""

from __future__ import annotations

import json
import os
from typing import Any

import structlog
from fastmcp import FastMCP

from app.config import settings
from app.mcp.auth import MCPAuthError, authenticate_api_key, check_scopes
from app.mcp.errors import auth_error

logger = structlog.stdlib.get_logger()


def _log_tool_call(tool: str, tenant_id: str, **extra: object) -> None:
    """Log an MCP tool call if logging is enabled."""
    if settings.MCP_LOG_TOOL_CALLS:
        logger.info("mcp_tool_call", tool=tool, tenant_id=tenant_id, **extra)


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

            # Per-tenant MCP rate limiting
            from app.api.rate_limit import _check_rate
            from app.mcp.errors import tool_error as _tool_error

            tenant_id_str = str(tenant.id)
            key = f"rl:mcp:{tenant_id_str}"
            count = await _check_rate(key, settings.MCP_RATE_LIMIT_REQUESTS, 60)
            if count > settings.MCP_RATE_LIMIT_REQUESTS:
                raise _tool_error(
                    "Rate limit exceeded",
                    hint=f"MCP limit is {settings.MCP_RATE_LIMIT_REQUESTS} requests/min. Retry after a moment.",
                )

            return api_key, tenant, db
        except MCPAuthError as exc:
            await db.close()
            raise auth_error(exc.detail) from exc
        except Exception:
            await db.close()
            raise

    # ── AI Tools ─────────────────────────────────────────────

    @mcp.tool(tags={"ai"})
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
            _log_tool_call("ai_complete", str(tenant.id), model=model)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"ai"})
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
            _log_tool_call("ai_list_models", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"ai"})
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
            _log_tool_call("ai_get_usage", str(tenant.id), days=days)
            return json.dumps(result)
        finally:
            await db.close()

    # ── Job Tools ────────────────────────────────────────────

    @mcp.tool(tags={"jobs"})
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
            _log_tool_call("job_create", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"jobs"})
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
            _log_tool_call("job_list", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"jobs"})
    async def job_get(job_id: str) -> str:
        """Get full details of a job by its ID.

        Returns status, payload, result, and error information.
        """
        from app.mcp.tools.jobs import job_get as _job_get

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "jobs:read")
            result = await _job_get(job_id=job_id, tenant=tenant, db=db)
            _log_tool_call("job_get", str(tenant.id), job_id=job_id)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"jobs"})
    async def job_cancel(job_id: str) -> str:
        """Cancel a pending or processing job.

        Only jobs that haven't completed can be cancelled.
        """
        from app.mcp.tools.jobs import job_cancel as _job_cancel

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "jobs:write")
            result = await _job_cancel(job_id=job_id, tenant=tenant, db=db)
            _log_tool_call("job_cancel", str(tenant.id), job_id=job_id)
            return json.dumps(result)
        finally:
            await db.close()

    # ── Billing Tools ────────────────────────────────────────

    @mcp.tool(tags={"billing"})
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
            _log_tool_call("billing_get_wallet_balance", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"billing"})
    async def billing_list_plans() -> str:
        """List all available subscription plans with pricing and limits."""
        from app.mcp.tools.billing import billing_list_plans as _list_plans

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "billing:read")
            result = await _list_plans(db=db)
            _log_tool_call("billing_list_plans", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"billing"})
    async def billing_get_subscription() -> str:
        """Get the current subscription details including plan and status."""
        from app.mcp.tools.billing import billing_get_subscription as _get_sub

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "billing:read")
            result = await _get_sub(tenant=tenant, db=db)
            _log_tool_call("billing_get_subscription", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    # ── File Tools ───────────────────────────────────────────

    @mcp.tool(tags={"files"})
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
            _log_tool_call("file_upload", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"files"})
    async def file_download(file_key: str) -> str:
        """Download a file by its key. Returns base64-encoded content."""
        from app.mcp.tools.files import file_download as _file_download

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "files:read")
            result = await _file_download(file_key=file_key, tenant=tenant, db=db)
            _log_tool_call("file_download", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"files"})
    async def file_list(prefix: str | None = None) -> str:
        """List uploaded files, optionally filtered by prefix."""
        from app.mcp.tools.files import file_list as _file_list

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "files:read")
            result = await _file_list(prefix=prefix, tenant=tenant, db=db)
            _log_tool_call("file_list", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    # ── Team Tools ───────────────────────────────────────────

    @mcp.tool(tags={"team"})
    async def team_list_members() -> str:
        """List all members of the current team with roles and emails."""
        from app.mcp.tools.team import team_list_members as _list_members

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "team:read")
            result = await _list_members(tenant=tenant, db=db)
            _log_tool_call("team_list_members", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"team"})
    async def team_invite(email: str, role: str = "member") -> str:
        """Invite a user to the team by email.

        Creates a pending invitation. Valid roles: member, admin.
        """
        from app.mcp.tools.team import team_invite as _team_invite

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "team:write")
            result = await _team_invite(email=email, role=role, tenant=tenant, db=db)
            _log_tool_call("team_invite", str(tenant.id), email=email)
            return json.dumps(result)
        finally:
            await db.close()

    # ── Webhook Tools ───────────────────────────────────────

    @mcp.tool(tags={"webhooks"})
    async def webhook_list() -> str:
        """List all configured webhook endpoints for the tenant."""
        from app.mcp.tools.webhooks import webhook_list as _webhook_list

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "webhooks:read")
            result = await _webhook_list(tenant=tenant, db=db)
            _log_tool_call("webhook_list", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"webhooks"})
    async def webhook_create(url: str, events: list[str], description: str | None = None) -> str:
        """Create a webhook endpoint to receive event notifications.

        Subscribe to events like job.completed, file.uploaded, member.added.
        The URL must be HTTPS and publicly reachable.

        Example: webhook_create(url="https://example.com/hook", events=["job.completed"])
        """
        from app.mcp.tools.webhooks import webhook_create as _webhook_create

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "webhooks:write")
            result = await _webhook_create(
                url=url, events=events, description=description, tenant=tenant, db=db,
            )
            _log_tool_call("webhook_create", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"webhooks"})
    async def webhook_delete(webhook_id: str) -> str:
        """Delete a webhook endpoint by ID."""
        from app.mcp.tools.webhooks import webhook_delete as _webhook_delete

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "webhooks:write")
            result = await _webhook_delete(webhook_id=webhook_id, tenant=tenant, db=db)
            _log_tool_call("webhook_delete", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    # ── Configurator Tools ─────────────────────────────────────

    @mcp.tool(tags={"configurator"})
    async def config_create_product(name: str, slug: str, description: str = "", sku_prefix: str = "", family_id: str = "") -> str:
        """Create a configurable product. Returns the product ID, name, and slug."""
        from app.mcp.tools.configurator import config_create_product as _create

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await _create(name=name, slug=slug, description=description, sku_prefix=sku_prefix, family_id=family_id or None, tenant=tenant, db=db)
            _log_tool_call("config_create_product", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_list_products(status: str = "", limit: int = 50) -> str:
        """List products for the tenant. Optionally filter by status (draft, active, deprecated, archived)."""
        from app.mcp.tools.configurator import config_list_products as _list

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:read")
            result = await _list(status=status or None, limit=limit, tenant=tenant, db=db)
            _log_tool_call("config_list_products", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_get_product(product_id: str) -> str:
        """Get product with characteristics, constraints, and BOMs."""
        from app.mcp.tools.configurator import config_get_product as _get

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:read")
            result = await _get(product_id=product_id, tenant=tenant, db=db)
            _log_tool_call("config_get_product", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_create_characteristic(
        name: str,
        slug: str,
        char_type: str,
        group_id: str = "",
        values: str = "[]",
        numeric_min: float | None = None,
        numeric_max: float | None = None,
        numeric_step: float | None = None,
        unit: str = "",
        is_required: bool = False,
        is_multi_select: bool = False,
        default_value: str = "",
        description: str = "",
    ) -> str:
        """Create a characteristic (configurable option). char_type: enum, numeric, boolean, text. For enum, pass values as JSON array of {value, label, description?, is_default?, price_adjustment?}."""
        from app.mcp.tools.configurator import config_create_characteristic as _create

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:write")
            parsed_values = json.loads(values) if values and values != "[]" else []
            result = await _create(
                name=name, slug=slug, char_type=char_type, group_id=group_id or None,
                values=parsed_values, numeric_min=numeric_min, numeric_max=numeric_max,
                numeric_step=numeric_step, unit=unit or None, is_required=is_required,
                is_multi_select=is_multi_select, default_value=default_value or None,
                description=description, tenant=tenant, db=db,
            )
            _log_tool_call("config_create_characteristic", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_assign_characteristic(product_id: str, characteristic_id: str, display_order: int = 0, is_required: bool | None = None, default_value: str = "") -> str:
        """Assign a characteristic to a product with optional overrides."""
        from app.mcp.tools.configurator import config_assign_characteristic as _assign

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await _assign(product_id=product_id, characteristic_id=characteristic_id, display_order=display_order, is_required=is_required, default_value=default_value or None, tenant=tenant, db=db)
            _log_tool_call("config_assign_characteristic", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_list_characteristics(product_id: str = "") -> str:
        """List characteristics, optionally filtered by product assignment."""
        from app.mcp.tools.configurator import config_list_characteristics as _list

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:read")
            result = await _list(product_id=product_id or None, tenant=tenant, db=db)
            _log_tool_call("config_list_characteristics", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_create_constraint_rule(
        product_id: str,
        name: str,
        constraint_type: str,
        expression: str,
        group_id: str = "",
        description: str = "",
        priority: int = 10,
    ) -> str:
        """Create a constraint rule with JSONB AST expression. constraint_type: requires, excludes, selection_condition, default_value, formula, table. expression: JSON string of the AST. Example REQUIRES: {"type":"requires","if":{"char":"engine","op":"eq","value":"V8"},"then":{"char":"transmission","op":"in","value":["auto_6","auto_8"]}}"""
        from app.mcp.tools.configurator import config_create_constraint_rule as _create

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:write")
            parsed_expr = json.loads(expression)
            result = await _create(product_id=product_id, name=name, constraint_type=constraint_type, expression=parsed_expr, group_id=group_id or None, description=description, priority=priority, tenant=tenant, db=db)
            _log_tool_call("config_create_constraint_rule", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_validate_constraints(product_id: str) -> str:
        """Validate constraints for a product: detect cycles, dead values, coverage gaps."""
        from app.mcp.tools.configurator import config_validate_constraints as _validate

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:read")
            result = await _validate(product_id=product_id, tenant=tenant, db=db)
            _log_tool_call("config_validate_constraints", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_simulate_configuration(product_id: str, selections: str) -> str:
        """Simulate constraint propagation. selections: JSON string of {char_slug: value} pairs."""
        from app.mcp.tools.configurator import config_simulate_configuration as _simulate

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:read")
            parsed_selections = json.loads(selections)
            result = await _simulate(product_id=product_id, selections=parsed_selections, tenant=tenant, db=db)
            _log_tool_call("config_simulate_configuration", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_create_bom_header(product_id: str, name: str, description: str = "", bom_type: str = "manufacturing", is_primary: bool = True) -> str:
        """Create a 150%% super BOM header for a product."""
        from app.mcp.tools.configurator import config_create_bom_header as _create

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await _create(product_id=product_id, name=name, description=description, bom_type=bom_type, is_primary=is_primary, tenant=tenant, db=db)
            _log_tool_call("config_create_bom_header", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_create_bom_item(
        bom_header_id: str,
        part_number: str,
        part_name: str,
        quantity: float = 1.0,
        selection_condition: str = "",
        item_type: str = "component",
        parent_item_id: str = "",
        description: str = "",
        unit_of_measure: str = "EA",
        unit_cost: float | None = None,
    ) -> str:
        """Add a BOM item. selection_condition: JSON AST for when this item is included (e.g. {"char":"engine","op":"eq","value":"V8"}). Empty = always included."""
        from app.mcp.tools.configurator import config_create_bom_item as _create

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:write")
            parsed_condition = json.loads(selection_condition) if selection_condition else None
            result = await _create(
                bom_header_id=bom_header_id, part_number=part_number, part_name=part_name,
                quantity=quantity, selection_condition=parsed_condition, item_type=item_type,
                parent_item_id=parent_item_id or None, description=description,
                unit_of_measure=unit_of_measure, unit_cost=unit_cost, tenant=tenant, db=db,
            )
            _log_tool_call("config_create_bom_item", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_create_bom_items_batch(bom_header_id: str, items: str) -> str:
        """Batch-create BOM items. items: JSON array of item objects (same fields as config_create_bom_item)."""
        from app.mcp.tools.configurator import config_create_bom_items_batch as _batch

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:write")
            parsed_items = json.loads(items)
            result = await _batch(bom_header_id=bom_header_id, items=parsed_items, tenant=tenant, db=db)
            _log_tool_call("config_create_bom_items_batch", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_create_variant_table(
        product_id: str,
        name: str,
        columns: str,
        rows: str,
        input_columns: str,
        output_columns: str,
        description: str = "",
    ) -> str:
        """Create a variant table for tabular constraint lookups. columns: JSON array of {name, type}. rows: JSON array of row objects. input_columns/output_columns: JSON arrays of column names."""
        from app.mcp.tools.configurator import config_create_variant_table as _create

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await _create(
                product_id=product_id, name=name, columns=json.loads(columns),
                rows=json.loads(rows), input_columns=json.loads(input_columns),
                output_columns=json.loads(output_columns), description=description,
                tenant=tenant, db=db,
            )
            _log_tool_call("config_create_variant_table", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_create_pricing_rule(
        product_id: str,
        name: str,
        rule_type: str,
        expression: str,
        priority: int = 10,
        currency: str = "EUR",
        description: str = "",
    ) -> str:
        """Create a pricing rule. rule_type: base_price, option_surcharge, volume_discount, conditional, formula, tiered, margin. expression: JSON rule definition."""
        from app.mcp.tools.configurator import config_create_pricing_rule as _create

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await _create(
                product_id=product_id, name=name, rule_type=rule_type,
                expression=json.loads(expression), priority=priority,
                currency=currency, description=description, tenant=tenant, db=db,
            )
            _log_tool_call("config_create_pricing_rule", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def config_create_version_snapshot(product_id: str, label: str = "") -> str:
        """Create a version snapshot of a product's configuration model for rollback."""
        from app.mcp.tools.configurator import config_create_version_snapshot as _create

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await _create(product_id=product_id, label=label, tenant=tenant, db=db)
            _log_tool_call("config_create_version_snapshot", str(tenant.id))
            return json.dumps(result)
        finally:
            await db.close()

    # ── Resources ────────────────────────────────────────────

    @mcp.resource("cadprice://models")
    async def resource_models() -> str:
        """Available AI models and their capabilities."""
        from app.mcp.tools.ai import ai_list_models as _ai_list_models

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "ai:read")
            result = await _ai_list_models(tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.resource("cadprice://wallet/balance")
    async def resource_wallet_balance() -> str:
        """Current token wallet balance."""
        from app.mcp.tools.billing import billing_get_wallet_balance as _get_balance

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "ai:read")
            result = await _get_balance(tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.resource("cadprice://team/members")
    async def resource_team_members() -> str:
        """Current team members with roles."""
        from app.mcp.tools.team import team_list_members as _list_members

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "team:read")
            result = await _list_members(tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.resource("cadprice://jobs/recent")
    async def resource_recent_jobs() -> str:
        """Most recent jobs (last 20)."""
        from app.mcp.tools.jobs import job_list as _job_list

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "jobs:read")
            result = await _job_list(limit=20, tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.resource("cadprice://billing/usage")
    async def resource_billing_usage() -> str:
        """AI usage statistics for the last 30 days."""
        from app.mcp.tools.ai import ai_get_usage as _ai_get_usage

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "ai:read")
            result = await _ai_get_usage(days=30, tenant=tenant, db=db)
            return json.dumps(result)
        finally:
            await db.close()

    @mcp.resource("cadprice://webhooks/events")
    async def resource_webhook_events() -> str:
        """Available webhook event types that can be subscribed to."""
        from app.api.v1.webhooks import VALID_WEBHOOK_EVENTS

        return json.dumps({"events": VALID_WEBHOOK_EVENTS})

    # ── Prompts ──────────────────────────────────────────────

    @mcp.prompt()
    async def list_available_prompts() -> str:
        """List the tenant's saved prompt templates for AI completions."""
        from sqlalchemy import select

        from app.db.models.ai import PromptTemplate

        api_key, tenant, db = await _get_context()
        try:
            check_scopes(api_key, "ai:read")
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

    @mcp.prompt()
    async def analyze_usage() -> str:
        """Prompt template: Analyze your AI usage patterns and suggest optimizations.

        Use this to understand your spending and identify cost-saving opportunities.
        """
        return json.dumps({
            "name": "analyze_usage",
            "description": "Analyze AI usage patterns and spending",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Analyze my AI usage data and provide:\n"
                        "1. Total spend and token usage trends\n"
                        "2. Most-used models and their cost efficiency\n"
                        "3. Suggestions to reduce costs\n\n"
                        "First call ai_get_usage and billing_get_wallet_balance, "
                        "then provide the analysis."
                    ),
                }
            ],
        })

    @mcp.prompt()
    async def troubleshoot_job() -> str:
        """Prompt template: Diagnose why a job failed and suggest fixes.

        Use this when a background job has failed and you need to understand why.
        """
        return json.dumps({
            "name": "troubleshoot_job",
            "description": "Diagnose a failed job and suggest remediation",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "A job has failed. Please:\n"
                        "1. Call job_list with status='failed' to find recent failures\n"
                        "2. Call job_get on the failed job to see the error\n"
                        "3. Explain the root cause and suggest how to fix it\n"
                        "4. If appropriate, suggest retrying with corrected parameters"
                    ),
                }
            ],
        })

    @mcp.prompt()
    async def optimize_costs() -> str:
        """Prompt template: Review billing and suggest plan/model optimizations.

        Use this to get recommendations on reducing costs or upgrading plans.
        """
        return json.dumps({
            "name": "optimize_costs",
            "description": "Review billing and suggest optimizations",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Review my billing and usage to optimize costs:\n"
                        "1. Call billing_get_wallet_balance to check token balance\n"
                        "2. Call billing_get_subscription to see current plan\n"
                        "3. Call billing_list_plans to see available plans\n"
                        "4. Call ai_get_usage to see usage patterns\n"
                        "5. Recommend whether to change plans or switch models "
                        "for better cost efficiency"
                    ),
                }
            ],
        })

    return mcp
