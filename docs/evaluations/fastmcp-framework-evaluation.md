# Evaluation: Replacing Current MCP Setup with PrefectHQ/FastMCP

**Date:** 2026-03-17
**Status:** Evaluation Complete
**Recommendation:** Do NOT migrate — the benefits are marginal and the risks outweigh them.

---

## Executive Summary

Our current MCP server is built on `mcp.server.fastmcp.FastMCP` from the **official MCP SDK** (`mcp[cli]>=1.0,<2`). PrefectHQ's standalone FastMCP (`fastmcp>=3.1`) is an evolution of the same original codebase — FastMCP 1.0 was incorporated into the official SDK in 2024, after which the standalone project diverged into v2/v3 with additional features. This evaluation assesses whether migrating to the standalone package would meaningfully improve our system.

---

## Current Architecture

| Aspect | Details |
|--------|---------|
| **Package** | `mcp[cli]>=1.0,<2` (official MCP Python SDK) |
| **Import** | `from mcp.server.fastmcp import FastMCP` |
| **Tools** | 22 tools across 6 domains (AI, jobs, billing, files, team, webhooks) |
| **Resources** | 8 read-only resources |
| **Prompts** | 4 system prompts |
| **Transports** | stdio + streamable-http |
| **Auth** | Custom API-key auth via `_get_context()` per tool call |
| **Rate Limiting** | Redis-backed, 300 req/min per tenant |
| **Error Handling** | Custom JSON-RPC error codes with agent-friendly hints |
| **Validation** | Pydantic schemas for all tool inputs |
| **Code Sharing** | Tools delegate to same domain services as REST API |

**Key files:**
- `app/mcp/server.py` — Server creation, tool/resource/prompt registration
- `app/mcp/run.py` — CLI entry point, transport selection
- `app/mcp/auth.py` — API key validation, scope checking
- `app/mcp/errors.py` — JSON-RPC error code mapping
- `app/mcp/schemas.py` — Pydantic input validation
- `app/mcp/tools/*.py` — Domain-specific tool implementations

---

## What PrefectHQ/FastMCP v3.1 Adds Over the Official SDK

### Features We Would Gain

| Feature | Description | Value to Us |
|---------|-------------|-------------|
| **Server Composition** | `mount()` to combine multiple servers; `create_proxy()` for remote servers | **Low** — We have a single monolithic MCP server; no multi-server composition need |
| **Built-in Client** | Programmatic MCP client with full protocol support | **Low** — We don't consume other MCP servers |
| **Apps (Interactive UIs)** | Render interactive UIs directly in conversations | **None** — Our MCP server is a backend API, not a conversational UI |
| **Tag-based Filtering** | Expose subsets of tools based on tags | **Low** — We use scope-based access control which is more granular |
| **OpenTelemetry Built-in** | Native observability instrumentation | **Low** — We already have OTel instrumentation in our service layer |
| **Provider Integrations** | Optional Anthropic/OpenAI/Gemini client wrappers | **None** — We use LiteLLM as our unified AI gateway |
| **Dynamic Composition** | Hot-add tools to mounted servers | **None** — Our tools are static and defined at startup |
| **Namespace Management** | Automatic prefixing to avoid naming collisions | **None** — Single server, no collision risk |
| **Custom HTTP Routes** | `@server.custom_route()` for non-MCP endpoints | **None** — We use FastAPI for all HTTP endpoints |

### Features That Overlap (We Already Have)

| Feature | Our Implementation | FastMCP v3 |
|---------|-------------------|------------|
| Tool registration | `@mcp.tool()` decorator | Same pattern |
| Resource registration | `@mcp.resource()` decorator | Same pattern |
| Prompt registration | `@mcp.prompt()` decorator | Same pattern |
| Input validation | Pydantic models in `schemas.py` | Auto-generated from type hints |
| Error handling | Custom `McpError` with JSON-RPC codes | Similar pattern |
| Transport support | stdio + streamable-http | Same + SSE |
| Auth | Custom per-call auth via `_get_context()` | Auth handlers (different pattern, same outcome) |

---

## Migration Risk Assessment

### Breaking Changes and Incompatibilities

1. **Different package, different import path**
   - Current: `from mcp.server.fastmcp import FastMCP`
   - FastMCP v3: `from fastmcp import FastMCP`
   - Every import in `server.py`, tests, and related files must change.

2. **Error handling API differences**
   - Current: `from mcp.shared.exceptions import McpError` / `from mcp.types import ErrorData`
   - FastMCP v3 may wrap or change these. Our custom error codes and hint system in `errors.py` would need validation.

3. **Dependency conflict risk**
   - FastMCP v3 depends on `mcp>=1.24.0,<2.0` — compatible with our `mcp[cli]>=1.0,<2`.
   - However, having both `mcp` and `fastmcp` as dependencies adds complexity. FastMCP v3 brings in additional transitive deps (authlib, websockets, uvicorn, httpx) — some we already have, but version conflicts are possible.

4. **Python version**
   - FastMCP requires Python >=3.10. We require >=3.11. Compatible, but worth noting.

5. **Auth pattern mismatch**
   - Our auth is deeply custom: env-var API key → DB lookup → tenant resolution → scope check → rate limit — all inside `_get_context()`.
   - FastMCP v3's auth system (if it has one) would need to support this exact flow or we'd still need our custom implementation. No clear advantage.

6. **Test suite impact**
   - 10+ test files in `tests/test_mcp/` test the current server, auth, errors, and all tools.
   - Migration would require revalidating all tests against the new framework's behavior.

### Effort Estimate

| Task | Scope |
|------|-------|
| Replace imports and update `FastMCP` usage | Small — but touches every MCP file |
| Validate error handling compatibility | Medium — custom JSON-RPC codes need testing |
| Update `pyproject.toml` dependencies | Small |
| Update `run.py` transport initialization | Small — may use different API |
| Revalidate and fix all MCP tests | Medium-Large — 10+ test files |
| Verify no regressions in auth, rate limiting, scopes | Medium |
| Update Docker/Makefile/docs | Small |
| **Total** | **~2-4 days of work + testing** |

---

## Decision Matrix

| Criterion | Weight | Current (`mcp` SDK) | FastMCP v3 | Winner |
|-----------|--------|---------------------|------------|--------|
| Stability / maturity for our use case | High | Proven in production | Newer, untested in our stack | Current |
| Feature completeness for our needs | High | All needs met | Superset, but extras unused | Tie |
| Auth flexibility | High | Fully custom, works perfectly | Would still need custom auth | Current |
| Maintenance burden | Medium | Minimal — stable SDK | Additional dependency to track | Current |
| Server composition | Low | Not needed | Strong, but not needed | N/A |
| Client features | Low | Not needed | Strong, but not needed | N/A |
| Community/ecosystem | Medium | Official SDK, broad adoption | Popular, actively maintained | Tie |
| Migration effort | High | Zero (status quo) | 2-4 days + risk | Current |

---

## Recommendation: Do Not Migrate

**Rationale:**

1. **We already use FastMCP** — the version bundled in the official MCP SDK is the original FastMCP 1.0. Our `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()` patterns are FastMCP patterns.

2. **The v3 additions don't solve problems we have.** Server composition, proxy creation, built-in clients, interactive apps, and tag filtering are powerful features — for a different kind of project. Our MCP server is a single-tenant-per-session backend with custom auth, scopes, and rate limiting that works well.

3. **Our custom abstractions are our strength.** The auth bridge (`auth.py`), error mapping (`errors.py`), structured logging, and domain-layer separation are tailored to our multi-tenant SaaS architecture. FastMCP v3's generic auth wouldn't replace them.

4. **Migration has real cost with no clear payoff.** 2-4 days of work, test revalidation, and deployment risk for features we don't need.

5. **Dependency simplicity matters.** Staying on the official `mcp` package means one less third-party dependency to track, fewer transitive deps, and alignment with the MCP specification's reference implementation.

### When to Reconsider

- If we need to **compose multiple MCP servers** (e.g., exposing different tool sets for different agent types)
- If we need to **proxy external MCP servers** through our platform
- If we need **interactive UI/app rendering** in agent conversations
- If the official `mcp` SDK's bundled FastMCP falls significantly behind the standalone version in core tool/resource/prompt functionality
- If FastMCP v3 adds built-in multi-tenant auth that matches our pattern

---

## Appendix: Package Comparison

| | Official `mcp` SDK | PrefectHQ `fastmcp` v3.1 |
|---|---|---|
| PyPI package | `mcp[cli]>=1.0,<2` | `fastmcp>=3.1` |
| Import | `from mcp.server.fastmcp import FastMCP` | `from fastmcp import FastMCP` |
| Origin | FastMCP 1.0 incorporated into SDK (2024) | Standalone continuation → v2 → v3 |
| Python | >=3.10 | >=3.10 |
| Depends on `mcp`? | Is `mcp` | Yes, `mcp>=1.24.0,<2.0` |
| Core MCP features | Tools, resources, prompts, transports | Same + composition, clients, apps |
| Stars | N/A (part of official SDK) | 23.8k |
| Downloads | Bundled with SDK | ~1M/day |
| License | MIT | Apache 2.0 |
