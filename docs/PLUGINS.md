# Plugin Guide

NEXUS is a platform foundation. Real applications live as **plugins** under `app/apps/<name>/`. The platform discovers them at startup and wires their routers, models, MCP tools, agent tools, capabilities, Celery configuration, scopes, error handlers, and frontend manifests into the running app.

The reference plugin lives at [`app/apps/example/`](../app/apps/example/). Copy it when you start a new application.

## Anatomy

```
app/apps/<name>/
├── __init__.py                empty
├── plugin.py                  PLUGIN = <YourPlugin>() — the only required file
├── api.py                     APIRouter contributing /api/v1/<name>/...
├── agent_tools.py             agent tool definitions + handlers
├── models/                    SQLAlchemy models (optional)
├── migrations/versions/       Alembic migrations (optional, if you have models)
└── ...

frontend/src/apps/<name>/      mirror layout for UI (optional)
├── components/
├── hooks/
├── routes/                    or contribute to the global routes/ tree
└── ...
```

## The contract

Every plugin subclasses [`AppPluginBase`](../app/plugins/base.py). Override only the hooks you need — every method has a sensible default.

| Hook | Returns | Purpose |
|---|---|---|
| `name` | `str` | Unique slug, e.g. `"crm"`, `"todo"`. Becomes the URL prefix and capability domain. |
| `version` | `str` | Semantic version. Logged at startup. |
| `display_name` | `str` | Human-readable label. Defaults to `name.upper()`. |
| `feature_flag` | `str` | Env var that enables/disables. Defaults to `APP_{NAME}_ENABLED`. Enabled when absent or truthy. |
| `get_routers()` | `list[APIRouter]` | FastAPI routers mounted under `/api/v1`. |
| `get_models()` | `list[type]` | SQLAlchemy classes (importing them is enough — they auto-register). |
| `get_mcp_tools(mcp, get_context)` | `None` | Register MCP tools on the shared `FastMCP`. |
| `get_mcp_bridge_config()` | `dict` | `{"allowed_tags": set, "allowed_path_prefixes": list}` to expose your routes via the FastAPI-MCP bridge. |
| `get_agent_tool_definitions()` | `dict[str, dict]` | Tools the agent runtime can invoke. Keys are tool names, values are JSON schemas. |
| `get_capability_domains()` | `list[CapabilityDomain]` | Group tools into human-friendly capabilities for the agent UI. |
| `invoke_tool(name, args, *, tenant, db)` | `Any` | Dispatch a plugin-owned agent tool by name. |
| `get_celery_config()` | `dict` | `{"autodiscover": [...], "task_routes": {...}, "beat_schedule": {...}}`. |
| `get_scopes()` | `list[str]` | API-key scopes this plugin contributes. |
| `get_event_handler_modules()` | `list[str]` | Module paths to import for side-effect event handler registration. |
| `get_frontend_manifest()` | `FrontendManifest \| None` | Sidebar nav items, etc. |
| `get_error_handlers()` | `list[(ExcType, handler)]` | Plugin-specific FastAPI exception handlers. |
| `get_plugin_config()` | `Any` | Your plugin's settings object (Pydantic model recommended). |
| `on_startup()` / `on_shutdown()` | `None` | Async lifecycle hooks. |
| `health_check()` | `dict` | `{"status": "ok"\|"degraded"\|"unhealthy", ...}` for `/health`. |

## Import-direction contract

Two rules, enforced by convention and by the plugin discovery boundary:

1. **Plugins may import from `app.core.*`, `app.db.*`, `app.ai.*`, `app.agents.*`, etc.** — they sit on top of the platform.
2. **Plugins must NEVER import from another `app.apps.*`.** Cross-app dependencies belong in `app.core.*` or in shared services exposed by the platform. Infrastructure code must never import from a plugin except via the registry.

Following these rules is what lets plugins be enabled/disabled with a feature flag and shipped from separate repositories.

## Walkthrough: build a "todo" plugin in 10 minutes

We'll build a tenant-scoped todo list. Three files.

### 1. `app/apps/todo/__init__.py`

Empty file (it's a Python package).

### 2. `app/apps/todo/plugin.py`

```python
from __future__ import annotations
from typing import Any, TYPE_CHECKING
from app.plugins.base import AppPluginBase, CapabilityDomain, FrontendManifest, NavItem, ToolCapability

if TYPE_CHECKING:
    from fastapi import APIRouter


class TodoPlugin(AppPluginBase):
    @property
    def name(self) -> str: return "todo"
    @property
    def version(self) -> str: return "0.1.0"
    @property
    def display_name(self) -> str: return "Todo"

    def get_routers(self) -> list["APIRouter"]:
        from app.apps.todo.api import router
        return [router]

    def get_agent_tool_definitions(self) -> dict[str, dict[str, Any]]:
        from app.apps.todo.agent_tools import TODO_TOOL_DEFINITIONS
        return TODO_TOOL_DEFINITIONS

    def get_capability_domains(self) -> list[CapabilityDomain]:
        return [
            CapabilityDomain(
                slug="todo",
                label="Todo",
                icon="ListChecks",
                capabilities=(
                    ToolCapability(
                        slug="todo:read",
                        label="View todos",
                        description="List the tenant's todos.",
                        tools=("todo_list",),
                    ),
                    ToolCapability(
                        slug="todo:write",
                        label="Manage todos",
                        description="Create and complete todos.",
                        tools=("todo_create", "todo_complete"),
                        risk_level="medium",
                    ),
                ),
            ),
        ]

    async def invoke_tool(self, tool_name, arguments, *, tenant, db):
        from app.apps.todo import agent_tools
        handler = getattr(agent_tools, tool_name, None)
        return await handler(**arguments, tenant=tenant, db=db) if handler else None

    def get_frontend_manifest(self) -> FrontendManifest:
        return FrontendManifest(
            nav_items=[NavItem(href="/todo", label_key="nav.todo", icon="ListChecks", order=50)],
        )


PLUGIN = TodoPlugin()
```

### 3. `app/apps/todo/api.py`

```python
from fastapi import APIRouter, Depends
from app.api.deps import get_current_tenant
from app.db.models.core import Tenant

router = APIRouter(prefix="/todo", tags=["todo"])


@router.get("")
async def list_todos(tenant: Tenant = Depends(get_current_tenant)) -> list[dict]:
    # Hook up your repository here. Tenant scoping is enforced by RLS as long
    # as you query through app.db.session.AsyncSessionLocal.
    return []
```

Restart the API. `/api/v1/todo` is mounted, the agent capability catalog gets a "Todo" domain, and the sidebar shows a Todo entry. Total: ~50 lines of code.

## Migrations

Plugins own their own DDL. Each plugin places Alembic migrations under `app/apps/<name>/migrations/versions/` and chains them into the core history via `down_revision`:

```python
# app/apps/todo/migrations/versions/0001_todo_schema.py
revision = "0001_todo_schema"
down_revision = "0001_basic_schema"   # or another migration in the chain
```

`app/db/migrations/env.py` automatically composes `version_locations` from the core path plus every enabled plugin's migration directory at import time, so `alembic upgrade head` walks the full graph in one pass.

Two rules to keep migrations safe:

- **Never reference plugin tables from a core migration.** If `app.db.migrations.versions.0001_basic_schema` ever needs to mention your tables, the platform has lost its application-agnostic property.
- **Never reference another plugin's tables from your migration.** Cross-app dependencies go through `app.core.*` or shared platform tables.

## Frontend layout

Frontend code mirrors the backend layout. Place app-specific code under `frontend/src/apps/<name>/`:

```
frontend/src/apps/<name>/
├── components/
├── hooks/
└── stores/
```

Routes can either live in `frontend/src/routes/<name>.*.tsx` (TanStack file-based router) or be lazy-loaded from your app's tree. Either way, **don't import from another app's tree**. Same rule as the backend.

The PWA, i18n, theme, and shared UI primitives are available from `@/components/ui/`, `@/lib/`, `@/hooks/`, etc. — use them.

## Settings

If your plugin needs configuration, expose a Pydantic `BaseSettings` and return it from `get_plugin_config()`. Use the `APP_<NAME>_` prefix for env vars to avoid collisions with the platform's `NXS_` prefix:

```python
# app/apps/todo/config.py
from pydantic_settings import BaseSettings

class TodoSettings(BaseSettings):
    APP_TODO_MAX_PER_TENANT: int = 1000
    APP_TODO_DEFAULT_DUE_DAYS: int = 7

    class Config:
        env_file = ".env"
        extra = "ignore"

todo_settings = TodoSettings()
```

## Testing

Plugin tests live alongside their plugin where possible: `app/apps/<name>/tests/` (collected by pytest as long as `tests/` discovery is broad enough). For tests that need the full platform — DB, Redis, lifespan — use `tests/conftest.py`'s fixtures.

The reference plugin can be smoke-tested with:

```bash
curl -sf http://localhost:8002/api/v1/example/ping \
  -H "Authorization: Bearer $NXS_API_KEY"
# {"plugin":"example","tenant_id":"...","message":"pong"}
```

## Disabling a plugin

```bash
APP_TODO_ENABLED=false make dev-up
```

The plugin's routers, models, MCP tools, agent tools, capability domains, scopes, and frontend manifest are **all** skipped. Migrations under the plugin's `migrations/versions/` directory are also skipped — but if those migrations have already been applied to a database, you must either keep the plugin enabled or run a manual cleanup (the platform doesn't auto-drop plugin tables).

## Shipping a plugin out of tree

A plugin can live in its own repository as long as it places its package under `app/apps/<name>/` at runtime. Two patterns work today:

1. **Vendored**: copy the plugin into `app/apps/<name>/` of a fork.
2. **Editable install**: structure the plugin as a Python package whose source ends up at `app/apps/<name>/` (e.g. via `pip install -e ./path/to/plugin-repo`).

The platform's `discover_plugins()` is path-based — it scans `app/apps/`. As long as the package and its `plugin.py` end up there, the discovery doesn't care whether the file came from this repo or a separate one.
