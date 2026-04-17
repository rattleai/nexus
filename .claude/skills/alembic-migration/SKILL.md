---
name: alembic-migration
description: Create, inspect, apply, and verify an Alembic migration. Use when a SQLModel table changes (new model, new column, renamed field, dropped index) or when the user asks to create/run a migration. Runs inside the backend container and requires the docker compose stack to be up. User-invoked only — never auto-triggers schema changes.
allowed-tools: Bash(docker compose exec backend *) Bash(uv run alembic *) Bash(ls backend/app/alembic/versions/*)
disable-model-invocation: true
argument-hint: "<message-describing-change>"
---

# Alembic Migration

Make schema changes traceable and reversible. Autogenerate is a starting point, not a final artifact.

## Prerequisites

- Docker stack running: `docker compose ps` shows `backend` and `db` healthy.
- Model changes saved in `backend/app/models.py`.
- Relationships updated on both sides.

## Workflow

### 1. Generate revision

```bash
docker compose exec backend alembic revision --autogenerate -m "$ARGUMENTS"
```

This creates `backend/app/alembic/versions/<hash>_<slug>.py`.

### 2. Read the generated file

Open the new revision and verify:

- **`upgrade()`** does what you expect — no missing columns, no spurious drops, no "alter" on unchanged fields.
- **`downgrade()`** correctly reverses — autogenerate often produces wrong downgrades for renames, constraint changes, and data migrations.
- **Data migrations** are absent unless you added them. If the schema change requires moving data, add the migration manually inside `upgrade()` using `op.execute(...)`.
- **Server defaults** present on any new NOT NULL column (see GOTCHAS).

### 3. Apply

```bash
docker compose exec backend alembic upgrade head
```

If this errors, the migration is broken. Do not commit it.

### 4. Verify against the DB

```bash
docker compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB -c '\d <table_name>'
```

Confirm columns, types, indexes, FKs match the model.

### 5. Round-trip test

```bash
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic upgrade head
```

Both must succeed. If downgrade fails, fix `downgrade()`.

### 6. Commit

Include the new file in `backend/app/alembic/versions/`. Commit message: `feat: add <X>` or `fix: alter <Y>`.

## What autogenerate misses (fix manually)

- **Column renames** → autogen produces `drop + add` (destroys data). Change to `op.alter_column(..., new_column_name=...)`.
- **Table renames** → same issue. Use `op.rename_table(...)`.
- **Enum changes** → Postgres enums require `ALTER TYPE ... ADD VALUE`; autogen won't write this.
- **Index renames** → silently ignored; add `op.execute("ALTER INDEX ... RENAME TO ...")`.
- **CHECK constraints** added via `sa.CheckConstraint(...)` — autogen detects add/drop but not changes.
- **Server-side computed columns / triggers** — autogen doesn't touch them.

## Safety rules

- **Never edit a migration that has been pushed.** Create a new one that corrects course.
- **Never `alembic downgrade base`** on anything but a throwaway dev DB.
- **NOT NULL additions to non-empty tables** require a three-step migration: add nullable → backfill with `op.execute(...)` → alter to NOT NULL.
- **Renames are destructive** unless explicitly written as renames. Read every autogen diff.
- **Large tables** — `CREATE INDEX` without `CONCURRENTLY` locks writes. Add `op.execute("CREATE INDEX CONCURRENTLY ...")` and use `op.create_index(..., postgresql_concurrently=True)`.

## Gotchas

- Autogenerate detects *class* changes, not *field reorderings*. Nothing happens if you reorder fields in the model.
- `server_default` must be a SQL expression (`"true"`, `"now()"`, `sa.text(...)`), not a Python value.
- `alembic upgrade head` succeeded but the app crashes — the migration applied but the model-to-DB sync is off. Run `\d <table>` to diff.
- Downgrade works in dev and fails in staging — production data has constraints dev doesn't. Test the downgrade on a data-heavy copy, not the empty dev DB.
- Multiple devs generating migrations on parallel branches → merge conflict at the `down_revision` header. Resolve by rebasing and regenerating with the new parent.
- "No changes detected" when you did change the model — Alembic didn't import your model. Check `backend/app/alembic/env.py` imports `app.models`.
