from collections.abc import AsyncGenerator

import structlog
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import Pool

from app.config import settings

logger = structlog.stdlib.get_logger()

# PostgreSQL server-side timeouts to prevent runaway queries and idle transactions
_PG_SERVER_SETTINGS = {
    "statement_timeout": "30000",  # 30s max query execution
    "idle_in_transaction_session_timeout": "60000",  # 60s idle-in-txn before kill
}

# Build connect_args with SSL support for production
_connect_args: dict = {"server_settings": _PG_SERVER_SETTINGS}
if settings.DATABASE_SSL_MODE:
    import ssl as _ssl
    if settings.DATABASE_SSL_MODE == "verify-full":
        # Full certificate verification (recommended for production)
        _ssl_ctx = _ssl.create_default_context()
        # check_hostname=True and verify_mode=CERT_REQUIRED are defaults
    elif settings.DATABASE_SSL_MODE == "require":
        # Encryption without certificate verification — vulnerable to MITM.
        # Use "verify-full" in production for proper server identity checks.
        _ssl_ctx = _ssl.create_default_context()
        _ssl_ctx.check_hostname = False
        _ssl_ctx.verify_mode = _ssl.CERT_NONE
    else:
        _ssl_ctx = _ssl.create_default_context()
    _connect_args["ssl"] = _ssl_ctx

async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=30,  # Wait max 30s for a connection from the pool
    connect_args=_connect_args,
)
async_session_factory = async_sessionmaker(async_engine, expire_on_commit=False)


# ── Connection pool monitoring (P0-8) ──────────────────────
# Emit metrics for pool utilization to detect silent pool exhaustion.

_pool_metrics_initialized = False


def setup_pool_monitoring(engine_to_monitor=None) -> None:
    """Register SQLAlchemy pool event listeners for monitoring.

    Exports metrics via OpenTelemetry meter if OTEL is enabled,
    otherwise logs pool events at debug level.
    """
    global _pool_metrics_initialized
    if _pool_metrics_initialized:
        return
    _pool_metrics_initialized = True

    target_engine = engine_to_monitor or async_engine

    # Get the sync pool from the async engine
    sync_pool = target_engine.sync_engine.pool

    _checkedout = 0
    _overflow = 0

    def _get_otel_gauges():
        """Lazily get OTEL gauges if available."""
        if not settings.OTEL_ENABLED:
            return None
        try:
            from app.core.telemetry import get_meter
            meter = get_meter()
            return {
                "checkedout": meter.create_up_down_counter(
                    "db.pool.connections.checkedout",
                    description="Number of connections currently checked out from the pool",
                ),
                "overflow": meter.create_up_down_counter(
                    "db.pool.connections.overflow",
                    description="Number of overflow connections currently in use",
                ),
                "invalidated": meter.create_counter(
                    "db.pool.connections.invalidated",
                    description="Total number of connections invalidated",
                ),
                "pool_size": meter.create_up_down_counter(
                    "db.pool.size",
                    description="Configured pool size",
                ),
            }
        except Exception:
            return None

    _gauges = None

    @event.listens_for(sync_pool, "checkout")
    def _on_checkout(dbapi_connection, connection_record, connection_proxy):
        nonlocal _checkedout, _gauges
        _checkedout += 1
        if _gauges is None:
            _gauges = _get_otel_gauges()
        if _gauges:
            _gauges["checkedout"].add(1)
        logger.debug(
            "db_pool_checkout",
            checkedout=_checkedout,
            pool_size=sync_pool.size(),
            overflow=sync_pool.overflow(),
            checkedin=sync_pool.checkedin(),
        )

    @event.listens_for(sync_pool, "checkin")
    def _on_checkin(dbapi_connection, connection_record):
        nonlocal _checkedout, _gauges
        _checkedout = max(0, _checkedout - 1)
        if _gauges:
            _gauges["checkedout"].add(-1)

    @event.listens_for(sync_pool, "invalidate")
    def _on_invalidate(dbapi_connection, connection_record, exception):
        nonlocal _gauges
        if _gauges is None:
            _gauges = _get_otel_gauges()
        if _gauges:
            _gauges["invalidated"].add(1)
        logger.warning("db_pool_connection_invalidated", exception=str(exception) if exception else None)

    @event.listens_for(sync_pool, "reset")
    def _on_reset(dbapi_connection, connection_record):
        pass  # Normal pool reset — no action needed

    logger.info("db_pool_monitoring_enabled", pool_size=settings.DB_POOL_SIZE, max_overflow=settings.DB_MAX_OVERFLOW)

# Read replica engine (optional — for read-write splitting)
_read_engine = None
_read_session_factory = None

if settings.DATABASE_READ_URL:
    _read_engine = create_async_engine(
        settings.DATABASE_READ_URL,
        echo=settings.DEBUG,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args=_connect_args,
    )
    _read_session_factory = async_sessionmaker(_read_engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def get_read_session() -> AsyncGenerator[AsyncSession]:
    """Get a read-only session (uses replica if configured, otherwise primary)."""
    factory = _read_session_factory or async_session_factory
    async with factory() as session:
        yield session


async def dispose_engines() -> None:
    """Dispose all database engines, releasing connection pools.

    Called during graceful shutdown to ensure connections are returned to the OS.
    """
    await async_engine.dispose()
    if _read_engine is not None:
        await _read_engine.dispose()


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """Set the tenant context for Row-Level Security.

    Must be called at the start of each request that uses tenant-scoped tables.
    Uses SET LOCAL so the setting is scoped to the current transaction.
    """
    # Use parameterized set_config() to prevent SQL injection via tenant_id
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )
