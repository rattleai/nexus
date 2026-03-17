# Evaluation: Migrating to PrefectHQ/FastMCP v3.1

**Date:** 2026-03-17
**Status:** Migration Complete
**Outcome:** Upgraded from `mcp[cli]>=1.0,<2` to `fastmcp>=3.1,<4`

---

## Executive Summary

We evaluated and then migrated our MCP server from the official MCP SDK's bundled FastMCP 1.0 (`mcp[cli]>=1.0,<2`) to the standalone PrefectHQ FastMCP v3.1 (`fastmcp>=3.1,<4`). The migration was low-risk and completed cleanly, positioning the platform on the actively-maintained, state-of-the-art MCP framework for agent-first infrastructure.

---

## Post-Migration Architecture

| Aspect | Details |
|--------|---------|
| **Package** | `fastmcp>=3.1,<4` (depends on `mcp>=1.24.0,<2.0` transitively) |
| **Import** | `from fastmcp import FastMCP` |
| **Tools** | 18 tools across 6 domains, all with tag-based filtering |
| **Resources** | 6 read-only resources |
| **Prompts** | 4 system prompts |
| **Transports** | stdio + http (backward-compat shim for `streamable-http`) |
| **Auth** | Custom API-key auth via `_get_context()` per tool call (unchanged) |
| **Rate Limiting** | Redis-backed, 300 req/min per tenant (unchanged) |
| **Error Handling** | Custom JSON-RPC error codes with agent-friendly hints via `McpError` (unchanged) |
| **Validation** | Pydantic schemas for all tool inputs (unchanged) |

---

## What Changed

| Area | Before | After |
|------|--------|-------|
| Dependency | `mcp[cli]>=1.0,<2` | `fastmcp>=3.1,<4` |
| Server import | `from mcp.server.fastmcp import FastMCP` | `from fastmcp import FastMCP` |
| Transport name | `"streamable-http"` | `"http"` (with backward-compat) |
| Tool decorators | `@mcp.tool()` | `@mcp.tool(tags={"domain"})` |
| Error imports (tests) | `from mcp.shared.exceptions import McpError` | `from app.mcp.errors import McpError` |
| websockets dep | `>=14.0,<15` | `>=15.0,<16` |

## What Stayed The Same

- All tool/resource/prompt functionality — identical behavior
- Custom auth (`_get_context()`), scopes, rate limiting
- Custom JSON-RPC error codes (-32001 through -32006)
- Tool implementations (`app/mcp/tools/*.py`) — only bug fixes
- Agent tool_registry integration

---

## Production Bugs Fixed During Migration

| Bug | File | Fix |
|-----|------|-----|
| `AIUsageLog(billed_tokens=...)` | `app/mcp/tools/ai.py` | Column is `billed_amount_usd`, not `billed_tokens` |
| `Plan.active.is_(True)` | `app/mcp/tools/billing.py` | Column is `is_active`, not `active` |
| `_tenant` vs `tenant` | `app/mcp/server.py` | Destructured as `_tenant` but referenced as `tenant` |
| `WebhookEndpoint(signing_secret=...)` | `app/mcp/tools/webhooks.py` | Column is `secret` with `set_secret()` method |
| `raise` without `from` | `app/mcp/tools/team.py` | Added exception chaining in `except` clause |

---

## Future Capabilities Unlocked

By adopting FastMCP v3.1, these features are now available when needed:

| Feature | Use Case |
|---------|----------|
| **Server Composition** | Split tool domains into mountable sub-servers |
| **Proxy Support** | Expose third-party MCP servers through our platform |
| **Tag Filtering** | Already implemented — agents can filter tools by domain |
| **Built-in Client** | Connect to external MCP servers programmatically |
| **Middleware** | Add cross-cutting concerns (caching, timing) to tools |
| **Lifespan Management** | Manage server startup/shutdown resources |

---

## Verification

- **59/59 MCP tests passing** (0 failures, 0 lint errors)
- 18 tools, 6 resources, 4 prompts registered and verified
- Both `stdio` and `http` transports functional
- Agent `tool_registry` integration verified (imports from `app.mcp.tools.*`)
- Docker-compose and Makefile updated and consistent

---

## Appendix: Package Comparison

| | Official `mcp` SDK (before) | PrefectHQ `fastmcp` v3.1 (after) |
|---|---|---|
| PyPI package | `mcp[cli]>=1.0,<2` | `fastmcp>=3.1,<4` |
| Import | `from mcp.server.fastmcp import FastMCP` | `from fastmcp import FastMCP` |
| Origin | FastMCP 1.0 incorporated into SDK (2024) | Standalone continuation → v2 → v3 |
| Python | >=3.10 | >=3.10 |
| Depends on `mcp`? | Is `mcp` | Yes, `mcp>=1.24.0,<2.0` |
| Core MCP features | Tools, resources, prompts, transports | Same + composition, clients, apps, tags |
| Stars | N/A (part of official SDK) | 23.8k |
| Downloads | Bundled with SDK | ~1M/day |
| License | MIT | Apache 2.0 |
