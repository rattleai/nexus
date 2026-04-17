---
name: sqlmodel-model
description: Add a new SQLModel table and its API schemas. Use when the user asks to add a model, table, entity, or database resource. Produces Base/Create/Update/Public/<Name>sPublic classes in backend/app/models.py, relationship updates on related models, a Alembic migration, CRUD helpers, and wiring notes. Invoke alembic-migration after the model is written.
argument-hint: "<model-name>"
paths: ["backend/app/models.py", "backend/app/crud.py", "backend/app/alembic/**"]
---

# SQLModel

Add a table model that matches this project's layering: five classes per resource, one table class, relationships declared on both ends, Alembic revision, CRUD helpers.

## The five-class pattern (see `backend/app/models.py:14-99`)

For a resource `Foo`:

```python
class FooBase(SQLModel):
    # Shared fields used in Create / Update / Public

class FooCreate(FooBase):
    # Fields accepted on POST

class FooUpdate(FooBase):
    # All fields optional; used on PATCH/PUT

class Foo(FooBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # FKs, relationships, server-only fields (hashed_*, created_at, ...)

class FooPublic(FooBase):
    id: uuid.UUID
    # Fields safe to return to clients

class FoosPublic(SQLModel):
    data: list[FooPublic]
    count: int
```

## Required patterns

- **IDs are `uuid.UUID`** with `default_factory=uuid.uuid4, primary_key=True`.
- **Timestamps use `get_datetime_utc`** and `sa_type=DateTime(timezone=True)` — see `models.py:9-11,52-55`.
- **String fields have `max_length=`** declared in both Base and Create/Update — SQLModel does not propagate it automatically.
- **Emails use `EmailStr`**, validated by pydantic.
- **Relationships are bidirectional**: `Relationship(back_populates="<name>")` on both sides. Use `cascade_delete=True` when child should die with parent (see `User.items` line 56).
- **Indexes**: add `index=True` to any field you'll filter on (email, owner_id).
- **Uniqueness**: `Field(unique=True, ...)` — remember this triggers an Alembic migration when changed.

## Do NOT

- Add a `Base` without inheriting from `SQLModel`.
- Put `str` without a `max_length` — Postgres accepts it but column type becomes unbounded varchar.
- Embed relationships in the Public class — serialization will loop.
- Name a table column `metadata` — reserved by SQLAlchemy.

## Workflow

1. **Declare the classes** in `backend/app/models.py`. Group in this order: Base → Create → Update → table class → Public → <Name>sPublic.
2. **Update relationships** on related tables (e.g., add `foos: list["Foo"] = Relationship(back_populates="owner")` on `User`).
3. **Add CRUD helpers** in `backend/app/crud.py` if logic is non-trivial. Thin routes, fat crud.
4. **Generate migration**: invoke `/alembic-migration` (or run `docker compose exec backend alembic revision --autogenerate -m "Add <Foo> model"`).
5. **Inspect the generated migration file** in `backend/app/alembic/versions/`. Autogenerate misses things — see GOTCHAS.md of alembic-migration.
6. **Apply** with `docker compose exec backend alembic upgrade head`.
7. **Verify downgrade**: `alembic downgrade -1` then `alembic upgrade head`. If downgrade fails, the migration is broken.
8. **Add endpoints** via `/fastapi-endpoint`.
9. **Tests** — unit test the CRUD helpers if any, route tests handle the rest.

## Gotchas

- Forward references in `Relationship` — use string form: `items: list["Item"]`, not `list[Item]` (class isn't defined yet).
- Adding a NOT NULL column without a server default on a non-empty table — Alembic will write `op.add_column(... nullable=False)` which fails on existing rows. Either make it nullable + backfill + alter, or provide `server_default=`.
- `is_active: bool = True` is a Python default, not a DB default. Existing rows get NULL. Add `server_default="true"` when in doubt.
- Changing a field from `str` to `EmailStr` doesn't change the DB schema, but breaks existing rows with bad data. Migrate the data.
- `sa_type=DateTime(timezone=True)` is required for tz-aware datetimes. Without it, Postgres stores naive timestamps.
- Unique constraint added on a column with duplicates — migration fails. Dedupe first.
