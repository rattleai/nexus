"""Ensure the non-superuser app_user role exists in PostgreSQL.

This script runs BEFORE alembic migrations using the superuser
(DATABASE_MIGRATION_URL). It idempotently creates the app_user role
and grants the necessary privileges so the application can connect
as a non-superuser with RLS enforcement.

Runs synchronously (no async engine needed) using the migration URL.
"""

import sys

from sqlalchemy import create_engine, text

from app.config import settings


def main() -> None:
    # Use the superuser migration URL to create the role
    url = settings.DATABASE_MIGRATION_URL or settings.DATABASE_URL
    # Convert async URL to sync for this one-off script
    sync_url = url.replace("+asyncpg", "+psycopg2").replace("+aiopg", "+psycopg2")

    engine = create_engine(sync_url)
    with engine.connect() as conn:
        # Check if app_user already exists
        result = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'app_user'")
        )
        if result.scalar_one_or_none():
            print("ensure_app_user: role 'app_user' already exists — skipping")
        else:
            conn.execute(
                text("CREATE ROLE app_user WITH LOGIN PASSWORD 'change-me-in-production'")
            )
            print("ensure_app_user: created role 'app_user'")
            conn.commit()

        # Grant privileges (idempotent)
        conn.execute(text("GRANT CONNECT ON DATABASE app TO app_user"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO app_user"))
        conn.execute(
            text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user")
        )
        conn.execute(
            text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user")
        )
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user"
            )
        )
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO app_user"
            )
        )
        conn.execute(
            text("GRANT EXECUTE ON FUNCTION set_config(text, text, boolean) TO app_user")
        )
        # Audit log immutability (defense-in-depth, idempotent)
        result = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_logs'")
        )
        if result.scalar_one_or_none():
            conn.execute(text("REVOKE UPDATE, DELETE ON audit_logs FROM app_user"))
        conn.commit()
        print("ensure_app_user: privileges granted")

    engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ensure_app_user: error — {e}", file=sys.stderr)
        # Non-fatal: don't block startup if this fails (e.g. no psycopg2)
        # The RLS check at app startup will catch if we're still superuser
        sys.exit(0)
