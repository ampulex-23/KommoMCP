"""Database session management."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kommo_mcp.config import init_settings

_engine = None
_async_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        settings = init_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=20,
            echo=settings.log_level == 'DEBUG',
        )
    return _engine

def _get_session_factory():
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Get database session."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def async_session_factory():
    """Get session factory (for compatibility)."""
    return _get_session_factory()


async def init_db() -> None:
    """Initialize database (create tables)."""
    from kommo_mcp.db.models import Base
    
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    engine = _get_engine()
    await engine.dispose()
