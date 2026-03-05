from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=300,
)
async_session_factory = async_sessionmaker(async_engine, expire_on_commit=False)

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
