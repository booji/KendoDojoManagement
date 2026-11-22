from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import DATABASE_URL


class _LazyAsyncEngine:
    """Stand-in for an AsyncEngine that defers create_async_engine() until
    the engine is actually used (first attribute access), rather than at
    import time.

    With no built-in fallback default, DATABASE_URL may be blank when this
    module is imported — that happens before app.main.lifespan calls
    app.config.validate_startup_config(). Building the real engine eagerly
    would make a blank DATABASE_URL surface as an opaque SQLAlchemy error at
    import time instead of the intended, named RuntimeError from
    validate_startup_config(). Deferring construction until first use lets
    validation run first while keeping `engine` a drop-in AsyncEngine for
    every existing caller.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._real: AsyncEngine | None = None

    def _get_real(self) -> AsyncEngine:
        if self._real is None:
            self._real = create_async_engine(self._url)
        return self._real

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_real(), name)


# The proxy forwards every attribute to a real AsyncEngine: one in all but name.
engine: AsyncEngine = _LazyAsyncEngine(DATABASE_URL)  # ty: ignore[invalid-assignment]

session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)
