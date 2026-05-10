import asyncio
import os
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Must be set before any app imports so token.py can read it
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not _DATABASE_URL.startswith("postgresql"):
    raise RuntimeError(
        "DATABASE_URL must be a PostgreSQL URL (postgresql+asyncpg://...). "
        "Run tests via: docker compose -f docker-compose.test.yml run --rm test"
    )
# Pin it back so load_dotenv() in app/config.py can't override it later.
os.environ["DATABASE_URL"] = _DATABASE_URL


@pytest.fixture(scope="session")
def database_url() -> str:
    return _DATABASE_URL


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


def pytest_collection_modifyitems(items: list) -> None:
    """Run unit/integration tests before e2e tests.

    Playwright's sync API uses a greenlet-based asyncio event loop that leaves
    asyncio.get_event_loop() returning a running loop while any playwright
    fixture is alive. Python 3.13 raises RuntimeError when any run_until_complete
    is attempted while another loop is running, breaking pytest-asyncio tests.
    Running non-e2e tests first avoids this conflict entirely.
    """
    e2e = [item for item in items if "/test_e2e_" in item.nodeid]
    non_e2e = [item for item in items if "/test_e2e_" not in item.nodeid]
    items[:] = non_e2e + e2e


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
    """Session-scoped async engine for tests that need to inspect engine metadata.

    Note: this engine is not used for schema setup (see _setup_schema) and must
    not be used inside async test functions if there is also a session event loop,
    as pooled connections are bound to the event loop in which they were created.
    """
    return create_async_engine(_DATABASE_URL)


@pytest.fixture(scope="session", autouse=True)
def _setup_schema():
    """Create all tables once per session using a short-lived event loop.

    Using a sync fixture with asyncio.run() avoids leaving an anyio session
    event loop in a running state, which would cause pytest-asyncio to fail
    when trying to run_until_complete on that same loop for later tests.
    """
    import app.attendance.db_models  # noqa: F401
    import app.auth.db_models  # noqa: F401
    import app.grades.db_models  # noqa: F401
    import app.members.db_models  # noqa: F401
    import app.sessions.db_models  # noqa: F401
    import app.settings.models  # noqa: F401
    from app.db.base import Base

    async def _create() -> None:
        engine = create_async_engine(_DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    async def _drop() -> None:
        engine = create_async_engine(_DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        finally:
            await engine.dispose()

    asyncio.run(_create())
    yield
    asyncio.run(_drop())


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Function-scoped async session with savepoint rollback for test isolation.

    Each test gets a fresh savepoint; on teardown the transaction is rolled back,
    leaving the database clean for the next test.

    Uses NullPool so every call creates a fresh asyncpg connection in the
    current (function-scoped) event loop.  The session-scoped pg_engine uses a
    standard pool whose connections are bound to the session event loop; reusing
    those pooled connections from a different loop causes InterfaceError.  By
    bypassing the pool entirely, db_session is always loop-safe.
    """
    engine = create_async_engine(_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            nested = await conn.begin_nested()

            session_factory = async_sessionmaker(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            session = session_factory()

            yield session

            await session.close()
            if nested.is_active:
                await nested.rollback()
            await trans.rollback()
    finally:
        await engine.dispose()
