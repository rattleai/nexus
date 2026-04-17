---
name: fastapi-endpoint
description: Scaffold a new FastAPI route for this project. Use when the user asks to add an endpoint, API route, create/read/update/delete, or CRUD for a resource in the backend. Produces a route file in backend/app/api/routes/, registers it in api/main.py, adds a matching test in backend/tests/api/routes/, and follows the existing SessionDep/CurrentUser/response_model conventions.
argument-hint: "<resource-name>"
paths: ["backend/app/api/**", "backend/tests/api/**"]
---

# FastAPI Endpoint

Scaffold a route that matches this project's conventions. See `backend/app/api/routes/items.py:1-120` for the reference implementation to mirror.

## Conventions to follow

Read these files once if you haven't already in this session:

- `backend/app/api/routes/items.py` — the canonical route file (list/get/create/update/delete with owner scoping).
- `backend/app/api/deps.py` — `SessionDep`, `CurrentUser`, `TokenDep`, `get_current_active_superuser`.
- `backend/app/crud.py` — where heavy DB logic goes; route files stay thin.
- `backend/app/models.py` — Base/Create/Update/Public/`<Name>sPublic` class pattern.
- `backend/tests/api/routes/test_items.py` — test structure.

## Required elements

### Route file at `backend/app/api/routes/<resource>.py`

```python
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    <Resource>,
    <Resource>Create,
    <Resource>Public,
    <Resource>sPublic,
    <Resource>Update,
    Message,
)

router = APIRouter(prefix="/<resources>", tags=["<resources>"])


@router.get("/", response_model=<Resource>sPublic)
def read_<resources>(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    ...
```

### Registration in `backend/app/api/main.py`

Add:

```python
from app.api.routes import <resource>
...
api_router.include_router(<resource>.router)
```

### Test file at `backend/tests/api/routes/test_<resource>.py`

Mirror `tests/api/routes/test_items.py`. Cover:

- Unauthenticated → 401.
- Non-owner → 404 on GET by id (when scoped), 403 on mutation.
- Owner → 200 on all CRUD.
- Superuser → 200 on all, including other users' resources if relevant.
- Validation errors → 422 with missing/invalid body.

## Admin-only endpoints

Replace `CurrentUser` with `Depends(get_current_active_superuser)` in the signature. See `backend/app/api/routes/users.py` for examples.

## Authorization pattern

Owner-scoped resources:

```python
if not current_user.is_superuser and (item.owner_id != current_user.id):
    raise HTTPException(status_code=403, detail="Not enough permissions")
```

For list endpoints, branch the query: superuser sees all, non-superuser sees own.

## Hard rules

- **No raw SQL.** Use `sqlmodel.select()`.
- **No `session.commit()` inside a try/except that swallows exceptions.**
- **Response model is required** on every endpoint — do not return raw dicts.
- **Use `*` to force keyword-only** on mutating endpoints (see `items.py:62`).
- **Route files are thin.** Any logic beyond CRUD goes in `app/crud.py`.
- **Register the router** in `api/main.py` or the endpoint will 404 silently.

## After scaffolding

1. Run `cd backend && uv run ruff format app/api/routes/<resource>.py tests/api/routes/test_<resource>.py`.
2. Run `cd backend && uv run mypy app/api/routes/<resource>.py`.
3. Run `docker compose exec backend bash scripts/tests-start.sh tests/api/routes/test_<resource>.py -x`.
4. If the OpenAPI schema changed, run `bash scripts/generate-client.sh` and include the client diff.
5. Invoke `/verify-before-done` before reporting complete.

## Gotchas

- Forgetting to include the router in `api/main.py` — the file exists, tests pass against the test client, and you still get 404 in curl. Always verify by hitting the live endpoint.
- Using `item.owner_id == current_user.id` before the `is_superuser` check — superuser shouldn't be blocked.
- Returning `item` without `response_model` set — leaks internal fields (hashed passwords, timestamps you didn't intend to expose).
- Creating a `<Resource>sPublic` wrapper type that doesn't include `count` — frontend pagination breaks.
- Putting business logic in the route — it gets untested and duplicated across methods.
