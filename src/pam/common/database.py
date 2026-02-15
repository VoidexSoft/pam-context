"""Async SQLAlchemy engine and session management."""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pam.common.config import settings


@lru_cache(maxsize=1)
def get_engine():
    """Return a cached async engine (created on first call)."""
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )


@lru_cache(maxsize=1)
def get_session_factory():
    """Return a cached session factory (created on first call)."""
    return async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


def reset_database() -> None:
    """Clear cached engine and session factory so they are re-created on next use."""
    get_engine.cache_clear()
    get_session_factory.cache_clear()


class _EngineProxy:
    """Proxy that delegates attribute access to the lazily-created engine."""

    def __getattr__(self, name: str) -> object:
        return getattr(get_engine(), name)

    def __repr__(self) -> str:
        return repr(get_engine())


class _SessionFactoryProxy:
    """Proxy that delegates attribute access and calls to the lazily-created factory."""

    def __call__(self, *args, **kwargs):
        return get_session_factory()(*args, **kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(get_session_factory(), name)

    def __repr__(self) -> str:
        return repr(get_session_factory())


engine = _EngineProxy()  # type: ignore[assignment]
async_session_factory = _SessionFactoryProxy()  # type: ignore[assignment]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
