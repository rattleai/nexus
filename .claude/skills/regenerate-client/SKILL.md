---
name: regenerate-client
description: Regenerate the frontend OpenAPI client after a backend API change. Use when an endpoint is added, removed, or modified in backend/app/api/routes/, or when the response/request schema of any endpoint changes. Runs scripts/generate-client.sh and surfaces breaking changes in the generated diff. User-invoked to avoid clobbering in-flight edits.
allowed-tools: Bash(bash scripts/generate-client.sh) Bash(bun run generate-client) Bash(git diff *) Bash(git status *)
disable-model-invocation: true
---

# Regenerate Client

Keep `frontend/src/client/` in sync with the backend's OpenAPI schema. This is the project's #2 source of "frontend broken after backend change" bugs.

## When to run

- After adding/removing a route in `backend/app/api/routes/`.
- After changing any `response_model`, `Create`/`Update`/`Public` schema, or endpoint signature.
- After updating an Alembic migration that changes a field's nullability, length, or shape.
- Before opening a PR that touches backend API surface.

## Prerequisites

- Docker stack running (the script hits `http://localhost:8000/api/v1/openapi.json`).
- Backend healthy: `curl -sf http://localhost:8000/api/v1/utils/health-check/` returns `true`.
- No in-flight manual edits to `frontend/src/client/` (the client is fully generated; manual edits are overwritten).

## Workflow

```bash
bash scripts/generate-client.sh
```

This script:

1. Fetches `openapi.json` from the running backend.
2. Runs `bun run generate-client` → `@hey-api/openapi-ts` regenerates `frontend/src/client/`.
3. Applies biome formatting.

## Review the diff

```bash
git diff frontend/src/client/
```

**Large auto-generated diff is normal** for schema changes. Scan for:

- **Added services / methods** → new endpoints you intended.
- **Removed services / methods** → only intentional if you deleted routes.
- **Changed type shapes** → may cause TypeScript errors in consumers — grep for usages.
- **Renamed methods** → autogen follows the route's `operation_id`; consumers break silently if you renamed without updating callers.

Then type-check the frontend:

```bash
cd frontend && bun x tsc --noEmit
```

Fix any call sites that now fail type-checking.

## Hard rules

- **Never edit `frontend/src/client/` by hand.** It's regenerated on every run. Any manual change is lost.
- **Commit the regenerated client alongside the backend change** — split PRs make CI fail in the gap.
- **Don't run this against a stale backend.** If your backend changes aren't picked up, the hot-reload didn't catch them. Restart the backend container.
- **`operation_id` matters.** FastAPI generates it from route-function names; changing a route function name renames the generated method. Keep names stable or update callers in the same change.

## Gotchas

- `ModuleNotFoundError: openapi_ts` → `bun install` wasn't run recently. Fix: `bun install` from repo root (bun workspace).
- Script reports success but client didn't update → backend hot-reload is serving stale OpenAPI. Restart: `docker compose restart backend && sleep 3 && bash scripts/generate-client.sh`.
- The generated client uses camelCase for method names; if a test references snake_case, the rename broke it — update the test.
- Adding `summary=` / `description=` to an endpoint changes the generated JSDoc but not function signatures — that diff is pure noise, commit it anyway to keep the client reproducible.
- CI regenerates the client and fails if uncommitted → always include the client diff in the same commit as the backend change.
