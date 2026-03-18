"""Testcontainers-based fixtures for integration tests with real PostgreSQL + Redis.

Spins up actual database and cache containers for each test session,
ensuring tests run against the same infrastructure as production.

Usage:
    pytest tests/ --containers   # enable testcontainers (off by default)

Requires:
    pip install testcontainers[postgres,redis]
"""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--containers",
        action="store_true",
        default=False,
        help="Use testcontainers for real PostgreSQL and Redis in tests",
    )


@pytest.fixture(scope="session")
def postgres_container(request):
    """Start a real PostgreSQL 16 container with pgvector for the test session."""
    if not request.config.getoption("--containers"):
        pytest.skip("Testcontainers not enabled (use --containers)")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        image="pgvector/pgvector:pg16",
        user="test",
        password="test",
        dbname="test",
    ) as pg:
        # Install pgvector extension
        import sqlalchemy

        engine = sqlalchemy.create_engine(pg.get_connection_url())
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        engine.dispose()

        yield pg


@pytest.fixture(scope="session")
def redis_container(request):
    """Start a real Redis 7 container for the test session."""
    if not request.config.getoption("--containers"):
        pytest.skip("Testcontainers not enabled (use --containers)")

    from testcontainers.redis import RedisContainer

    with RedisContainer(image="redis:7-alpine") as redis:
        yield redis


@pytest.fixture(scope="session")
def container_env(postgres_container, redis_container):
    """Set environment variables to point at the test containers."""
    pg_url = postgres_container.get_connection_url()
    async_pg_url = pg_url.replace("postgresql://", "postgresql+asyncpg://")

    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(6379)

    os.environ["DATABASE_URL"] = async_pg_url
    os.environ["DATABASE_SYNC_URL"] = pg_url
    os.environ["REDIS_URL"] = f"redis://{redis_host}:{redis_port}/0"

    yield {
        "database_url": async_pg_url,
        "database_sync_url": pg_url,
        "redis_url": f"redis://{redis_host}:{redis_port}/0",
    }
