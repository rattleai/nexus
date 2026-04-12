import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.db.base import Base
from app.plugins.registry import discover_plugins  # noqa: E402

# Discover plugins so their models register on Base.metadata
discover_plugins()

from app.db.models import *  # noqa: F401, F403 — register all models (infra + plugins)

config = context.config
# Migrations need superuser privileges (CREATE TABLE, ALTER, ENABLE RLS).
# Use DATABASE_MIGRATION_URL if set, otherwise fall back to DATABASE_URL.
_migration_url = settings.DATABASE_MIGRATION_URL or settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", _migration_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def widen_alembic_version_column(connection):
    """Ensure alembic_version.version_num is wide enough for long revisions.

    Runs in a dedicated transaction BEFORE alembic takes over the connection.
    Pre-creates the alembic_version table with VARCHAR(128) so that alembic's
    default CREATE TABLE (which uses VARCHAR(32)) is a no-op. Also widens the
    column on legacy databases where the table already exists with the
    narrow default.

    Background: some revision identifiers (e.g. 0021_cardinality_check_constraints,
    34 chars) exceed alembic's default VARCHAR(32). Without this fix, fresh
    bootstraps fail at revision 0021 with StringDataRightTruncationError, and
    legacy databases with the narrow column fail the same way during upgrade.
    """
    # Fresh DB path: create the table upfront with the wider column so alembic
    # sees it already exists and won't attempt its default VARCHAR(32) CREATE.
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS alembic_version ("
        "    version_num VARCHAR(128) NOT NULL, "
        "    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
        ")"
    )
    # Legacy DB path: table exists with VARCHAR(32) — widen it.
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
