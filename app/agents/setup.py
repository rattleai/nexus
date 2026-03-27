"""Shared agent setup helpers — tool executor, governance, and datasource resolution.

Extracted from ``AgentExecutor`` so both the async (Celery) and streaming
(SSE) execution paths can reuse the same logic without duplicating code.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Callable, Coroutine

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.stdlib.get_logger()

# Pattern: @[Display Name](ds:uuid) — injected by frontend source-mention-input
_DS_MENTION_RE = re.compile(r"@\[([^\]]+)\]\(ds:([0-9a-f\-]{36})\)")


def build_tool_executor(
    definition: Any,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]:
    """Build a tool executor callable: ``(tool_name, arguments) -> result``.

    The returned closure checks ``allowed_tools`` before dispatching to the
    tool registry, which routes to built-in, plugin, or tenant-external tools.
    """
    allowed_tools = set(definition.allowed_tools or [])

    async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
        if allowed_tools and tool_name not in allowed_tools:
            return {"error": f"Tool '{tool_name}' is not allowed for this agent"}

        try:
            from app.agents.tool_registry import tool_registry

            return await tool_registry.invoke(
                tool_name=tool_name,
                arguments=arguments,
                tenant_id=tenant_id,
                db=db,
            )
        except Exception as exc:
            logger.warning(
                "agent_tool_execution_failed",
                tool_name=tool_name,
                error=str(exc),
            )
            return {"error": f"Tool execution failed: {exc}"}

    return execute_tool


def build_governance_checker(
    definition: Any,
    tenant_id: uuid.UUID,
) -> Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]:
    """Build a governance checker callable: ``(action, context) -> None``.

    Raises ``GovernanceViolationError`` when a policy is violated.
    The governance engine is created once and reused across all checks.
    """
    from app.agents.governance import GovernanceEngine

    policy = definition.governance_policy or {}
    engine = GovernanceEngine(policy)

    async def check_governance(action: str, context: dict[str, Any]) -> None:
        await engine.check(action=action, context=context, tenant_id=tenant_id)

    return check_governance


async def resolve_datasource_mentions(
    messages: list[dict[str, Any]],
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Scan user messages for ``@[name](ds:uuid)`` patterns and inject source content.

    For each referenced data source:
    1. Load the DataSource record
    2. If extraction_result is cached, build a context summary
    3. If chunks exist, include the most relevant chunks
    4. Inject as a system message before the user message

    This gives agents focused access to exactly the data sources
    the user specified, similar to #file references in VS Code Copilot.
    """
    resolved: list[dict[str, Any]] = []

    for msg in messages:
        if msg.get("role") != "user" or not isinstance(msg.get("content"), str):
            resolved.append(msg)
            continue

        content = msg["content"]
        mentions = list(_DS_MENTION_RE.finditer(content))

        if not mentions:
            resolved.append(msg)
            continue

        # Resolve each mentioned data source
        for match in mentions:
            ds_name = match.group(1)
            ds_id_str = match.group(2)

            try:
                ds_id = uuid.UUID(ds_id_str)
                context_text = await _load_datasource_context(ds_id, tenant_id, db)
                if context_text:
                    resolved.append({
                        "role": "system",
                        "content": (
                            f"=== Data Source: {ds_name} (id: {ds_id_str}) ===\n"
                            f"{context_text}\n"
                            f"=== End Data Source: {ds_name} ==="
                        ),
                    })
            except Exception:
                logger.warning(
                    "datasource_mention_resolve_failed",
                    datasource_id=ds_id_str,
                    datasource_name=ds_name,
                    exc_info=True,
                )

        # Clean the mention syntax from the user message for readability
        clean_content = _DS_MENTION_RE.sub(r"@\1", content)
        resolved.append({**msg, "content": clean_content})

    return resolved


async def _load_datasource_context(
    datasource_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    max_chunks: int = 20,
    max_chars: int = 15_000,
) -> str | None:
    """Load content from a data source for injection into agent context.

    Returns a text summary of the data source content, prioritizing:
    1. Extracted tables (most useful for configuration)
    2. Extracted sections
    3. Raw text chunks
    """
    try:
        from app.db.models.datasource import DataSource, DataSourceChunk, DataSourceStatus
    except ImportError:
        logger.debug("datasource_models_not_available")
        return None

    stmt = select(DataSource).where(
        DataSource.id == datasource_id,
        DataSource.tenant_id == tenant_id,
        DataSource.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    ds = result.scalar_one_or_none()
    if not ds:
        return None

    if ds.status != DataSourceStatus.READY:
        return f"[Data source '{ds.name}' is not ready (status: {ds.status})]"

    # Use cached extraction result if available
    if ds.extraction_result:
        return _format_extraction_result(ds.extraction_result, max_chars)

    # Fall back to chunks
    chunk_stmt = (
        select(DataSourceChunk)
        .where(
            DataSourceChunk.data_source_id == datasource_id,
            DataSourceChunk.tenant_id == tenant_id,
        )
        .order_by(DataSourceChunk.chunk_index)
        .limit(max_chunks)
    )
    chunk_result = await db.execute(chunk_stmt)
    chunks = list(chunk_result.scalars().all())

    if not chunks:
        return None

    parts: list[str] = []
    total_chars = 0
    for chunk in chunks:
        if total_chars + len(chunk.content) > max_chars:
            parts.append(chunk.content[: max_chars - total_chars])
            break
        parts.append(chunk.content)
        total_chars += len(chunk.content)

    return "\n\n".join(parts)


def _format_extraction_result(extraction: dict, max_chars: int = 15_000) -> str:
    """Format a cached ExtractionResult dict into agent-readable text."""
    parts: list[str] = []
    total = 0

    # Tables first (most valuable for configuration)
    tables = extraction.get("tables", [])
    if tables:
        parts.append(f"## Extracted Tables ({len(tables)} found)\n")
        for i, table in enumerate(tables):
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            if not headers:
                continue
            md = f"### Table {i + 1}\n"
            md += "| " + " | ".join(headers) + " |\n"
            md += "| " + " | ".join("---" for _ in headers) + " |\n"
            for row in rows[:50]:  # Cap at 50 rows per table
                md += "| " + " | ".join(str(cell) for cell in row) + " |\n"
            if len(rows) > 50:
                md += f"\n... ({len(rows) - 50} more rows)\n"
            parts.append(md)
            total += len(md)
            if total > max_chars:
                break

    # Then sections
    sections = extraction.get("sections", [])
    if sections and total < max_chars:
        parts.append(f"\n## Extracted Sections ({len(sections)} found)\n")
        for section in sections:
            title = section.get("title", "Untitled")
            content = section.get("content", "")
            s = f"### {title}\n{content}\n"
            parts.append(s)
            total += len(s)
            if total > max_chars:
                break

    # Raw text fallback
    if not parts:
        raw = extraction.get("raw_text", "")
        if raw:
            parts.append(raw[:max_chars])

    return "\n".join(parts)
