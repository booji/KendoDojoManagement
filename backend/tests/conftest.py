import os
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Must be set before any app imports so token.py can read it
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not _DATABASE_URL.startswith("postgresql"):
    raise RuntimeError(
        "DATABASE_URL must be a PostgreSQL URL (postgresql+asyncpg://...). "
        "Run tests via: docker compose -f docker-compose.test.yml run --rm test"
    )


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


class _NoOpAttendanceRepo:
    """Stub attendance repo used as a default in unit tests that don't set one."""

    async def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return []

    async def check_in(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:  # pragma: no cover
        return {}

    async def get_by_session_member(
        self, session_id: str, member_id: str
    ) -> dict[str, Any] | None:  # pragma: no cover
        return None

    async def admin_mark_attended(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:  # pragma: no cover
        return {}

    async def remove_attendance(
        self, session_id: str, member_id: str
    ) -> bool:  # pragma: no cover
        return False

    async def add_visitor(
        self, session_id: str, visitor_name: str, recorded_by: str
    ) -> dict[str, Any]:  # pragma: no cover
        return {}

    async def list_for_member(
        self, member_id: str
    ) -> list[dict[str, Any]]:  # pragma: no cover
        return []


@pytest.fixture(autouse=True)
def _default_attendance_repo_stub():
    """Install a no-op attendance repo so tests that don't mock it don't hit the DB.

    Individual tests can override get_attendance_repo after this fixture runs.
    """
    from app.attendance.dependencies import get_attendance_repo
    from app.main import app

    stub = _NoOpAttendanceRepo()
    app.dependency_overrides.setdefault(get_attendance_repo, lambda: stub)
    yield
    # Teardown is handled by each test file's own clear_overrides fixture.


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset slowapi in-memory rate limit counters and per-account failure counts
    between tests so accumulated state from one test doesn't bleed into the next.
    """
    from app.main import app

    yield

    # Reset slowapi storage
    try:
        app.state.limiter._storage.reset()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# PostgreSQL integration fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_engine():
    return create_async_engine(_DATABASE_URL)


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _setup_schema(pg_engine):
    import app.attendance.db_models  # noqa: F401
    import app.auth.db_models  # noqa: F401
    import app.grades.db_models  # noqa: F401
    import app.members.db_models  # noqa: F401
    import app.sessions.db_models  # noqa: F401
    import app.settings.models  # noqa: F401
    from app.db.base import Base

    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session(pg_engine) -> AsyncSession:
    """Function-scoped async session with savepoint rollback for test isolation.

    Each test gets a fresh savepoint; on teardown the transaction is rolled back,
    leaving the database clean for the next test.
    """
    async with pg_engine.connect() as conn:
        await conn.begin()
        # Nested transaction = SAVEPOINT
        await conn.begin_nested()

        session_factory = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        session = session_factory()

        yield session

        await session.close()
        await conn.rollback()
