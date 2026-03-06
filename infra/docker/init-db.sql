-- PostgreSQL initialization script for multi-tenant SaaS platform.
--
-- Creates a non-superuser application role so that Row-Level Security (RLS)
-- policies are enforced. Superusers bypass RLS entirely, so the application
-- MUST connect as this restricted role in production.
--
-- This script runs once when the PostgreSQL container first initializes.
-- Mount it at /docker-entrypoint-initdb.d/init-db.sql in docker-compose.

-- Create the application database (idempotent — skipped if DB already exists)
SELECT 'CREATE DATABASE app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'app')\gexec

-- Create a non-superuser role for the application
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user WITH LOGIN PASSWORD 'change-me-in-production';
    END IF;
END
$$;

-- Grant necessary privileges
GRANT CONNECT ON DATABASE app TO app_user;

-- Switch to app database for schema-level grants
\connect app

-- Grant schema usage and table manipulation (no CREATE to prevent DDL outside migrations)
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- Ensure future tables/sequences are also accessible
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_user;

-- Allow the app to use set_config for RLS tenant context
GRANT EXECUTE ON FUNCTION set_config(text, text, boolean) TO app_user;
