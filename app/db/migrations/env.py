import asyncio
import os
import re
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.db.base import Base
from app.plugins.registry import discover_plugins, registry as plugin_registry

# Discover plugins so their models register on Base.metadata
discover_plugins()

from app.db.models import *  # noqa: F403 — register all models (infra + plugins)

config = context.config
# Migrations need superuser privileges (CREATE TABLE, ALTER, ENABLE RLS).
# Use DATABASE_MIGRATION_URL if set, otherwise fall back to DATABASE_URL.
_migration_url = settings.DATABASE_MIGRATION_URL or settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", _migration_url)

# Compose version_locations from the core path plus every enabled plugin
# that ships an `app/apps/<name>/migrations/versions/` directory. Plugin
# migration files chain into the core history via `down_revision`. See
# docs/PLUGINS.md, "Migrations".
_repo_root = Path(__file__).resolve().parents[3]
_version_locations: list[str] = [str(_repo_root / "app" / "db" / "migrations" / "versions")]
for _plugin in plugin_registry:
    _candidate = _repo_root / "app" / "apps" / _plugin.name / "migrations" / "versions"
    if _candidate.is_dir():
        _version_locations.append(str(_candidate))
config.set_main_option("version_locations", os.pathsep.join(_version_locations))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ── Autogenerate filter ──────────────────────────────────────────────
# Hash-partition children of `data_source_chunks` are created dynamically
# via raw DDL in 0001_basic_schema (CREATE TABLE ... PARTITION OF ...).
# PostgreSQL auto-propagates parent indexes to the partitions, and each
# partition gets its own HNSW indexes — none of which are declarable in
# the ORM (you cannot model "this table only exists because the parent
# partitions hash-distribute over N children" with SQLAlchemy classes).
#
# Without this filter, `alembic check` flags every partition table and
# every propagated/HNSW index as drift on every run, drowning out the
# genuine ORM-vs-migration diffs we actually want to see. Skipping them
# at the autogenerate boundary is the canonical fix — the migrations
# themselves still create and manage the partitions; we just exclude
# them from the *comparison* against ORM metadata.
_PARTITION_TABLE_RE = re.compile(r"^data_source_chunks_p\d+$")


def _include_object(object_, name, type_, reflected, compare_to):
    if type_ == "table" and name and _PARTITION_TABLE_RE.match(name):
        return False
    # Indexes attached to a partition table are reported with the
    # partition as their parent; filter them out too.
    if type_ == "index":
        table_name = getattr(getattr(object_, "table", None), "name", None) or ""
        if _PARTITION_TABLE_RE.match(table_name):
            return False
    # Foreign-key constraints: autogenerate often fails to round-trip the
    # `ondelete` option through PostgreSQL's reflected catalogs, producing
    # drop+recreate cycles that silently strip CASCADE / SET NULL clauses.
    # FK changes belong in hand-written migrations, not autogenerate.
    return type_ != "foreign_key_constraint"


def _compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    """Treat custom Postgres-native column types as equal to their reflected forms.

    Alembic's default type comparator cannot reconcile the ORM-side wrappers
    (VectorType, HalfvecType, TSVECTOR with `Mapped[str]`) against the
    `vector(N)` / `halfvec(N)` / `tsvector` types Postgres reflects out of
    its catalogs. Without this hook, autogenerate proposes a destructive
    drop+add of those columns on every run. Returning ``False`` here signals
    "no difference" so autogenerate leaves the column alone.
    """
    inspected_str = str(inspected_type).lower()
    metadata_str = str(metadata_type).lower()
    if "vector" in inspected_str or "vector" in metadata_str:
        return False
    if "halfvec" in inspected_str or "halfvec" in metadata_str:
        return False
    if "tsvector" in inspected_str or "tsvector" in metadata_str:
        return False
    return None  # defer to alembic's default comparator


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=_compare_type,
        include_object=_include_object,
        # Wider column for alembic_version on new deployments so revision
        # identifiers longer than 32 chars never get truncated.
        version_table_column_length=128,
    )
    with context.begin_transaction():
        context.run_migrations()


def widen_alembic_version_column(connection):
    """Ensure alembic_version.version_num is wide enough for long revisions.

    Runs in a dedicated transaction BEFORE alembic takes over the connection
    so it's fully committed and visible to alembic's own UPDATE statements.

    Fresh-DB path: pre-create alembic_version with VARCHAR(128) so alembic's
    default CREATE TABLE (VARCHAR(32)) becomes a no-op.

    Legacy-DB path: idempotently widen the column when an existing database
    still has the narrow default.

    Required because several revision IDs on this branch (e.g.
    ``0021_cardinality_check_constraints``, ``0028_connector_hardening``)
    exceed alembic's default VARCHAR(32).
    """
    # Fresh-DB path: create the table with the wider column upfront.
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS alembic_version ("
        "    version_num VARCHAR(128) NOT NULL, "
        "    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
        ")"
    )
    # Legacy-DB path: widen narrow column in place.
    connection.exec_driver_sql(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'alembic_version' AND column_name = 'version_num' "
        "AND character_maximum_length < 128) THEN "
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128); "
        "END IF; END $$;"
    )


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # Step 1: widen alembic_version column in a dedicated transaction.
    # This must complete and commit before alembic's migration context takes
    # over so the wider column is visible to the post-migration UPDATE.
    async with connectable.begin() as widen_conn:
        await widen_conn.run_sync(widen_alembic_version_column)

    # Step 2: run migrations using alembic's standard transaction management.
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
