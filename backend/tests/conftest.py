import asyncio
import os
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
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
# run_tests.sh gives each invocation its own throwaway database and drops it
# wholesale on exit (see run_tests.sh's cleanup()). A misdirected DATABASE_URL
# (e.g. the dev database) would be just as destructive if it were ever handed
# to that drop. Refuse to run against anything but a dedicated test database —
# its name must contain "test" (the compose test DB is "kendo_test").
_db_name = _DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0]
if "test" not in _db_name.lower():
    raise RuntimeError(
        f"Refusing to run tests against database {_db_name!r}: run_tests.sh "
        "drops this database wholesale on exit, which would destroy all of "
        "its data. Point DATABASE_URL at a dedicated test database (name "
        "containing 'test'), e.g. via docker compose -f docker-compose.test.yml."
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


@pytest.fixture()
def cookies_for():
    """Build a real signed access-token cookie for the given claims.

    Use this for any test asserting an *authorization* outcome. Overriding the
    guard under test (e.g. ``dependency_overrides[REQUIRE_ADMIN] = a member
    stub``) replaces the code that produces the 403, so the assertion ends up
    exercising whatever redundant role check happens to sit inside the route
    instead — such a test passes even if the route's guard is removed. Handing
    the real guard a real member token keeps the check honest.

    No DB is involved: the token is signed with the JWT_SECRET set above.
    """
    from app.auth.models import UserClaims
    from app.auth.token import encode_token

    def _make(claims: "UserClaims") -> dict[str, str]:
        return {"access_token": encode_token(claims)}

    return _make


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
    """Verify the schema is already migrated — conftest no longer builds it.

    run_tests.sh creates a fresh per-run database and starts uvicorn against
    it before pytest ever runs; uvicorn's own lifespan runs `alembic upgrade
    head` via app.db.bootstrap.prepare_database(), which is the sole schema
    owner (see the module docstring in test_conftest_schema_ownership.py for
    why two builders/teardowns racing each other was the actual bug in
    #316). By the time this fixture runs, the schema must already exist —
    all this does is check that and fail loudly, with one clear diagnostic,
    if it doesn't, rather than let every DB-touching test fail individually
    with its own confusing UndefinedTableError.

    Using a sync fixture with asyncio.run() avoids leaving an anyio session
    event loop in a running state, which would cause pytest-asyncio to fail
    when trying to run_until_complete on that same loop for later tests.
    """

    async def _check_schema_migrated() -> bool:
        engine = create_async_engine(_DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT to_regclass('public.alembic_version')")
                )
                return result.scalar() is not None
        finally:
            await engine.dispose()

    if not asyncio.run(_check_schema_migrated()):
        raise RuntimeError(
            "Database has no migrated schema (no 'alembic_version' table "
            "found). Tests must be run via run_tests.sh, which starts "
            "uvicorn first — its lifespan runs 'alembic upgrade head' "
            "before pytest is ever invoked. Run tests via: "
            "podman-compose -f docker-compose.test.yml run --rm test"
        )
    yield


class DbSessionUnitOfWork:
    """Adapts a raw AsyncSession (already inside a test savepoint) to the
    AbstractUnitOfWork protocol, without ending the surrounding transaction.

    Used by DB-backed tests to override `get_uow` so the app's own commit()
    calls just flush the shared, savepoint-scoped `db_session` instead of
    opening a separate connection/transaction — keeping everything inside
    the one savepoint that gets rolled back on teardown.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def commit(self) -> None:
        await self._session.flush()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def __aenter__(self) -> "DbSessionUnitOfWork":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest_asyncio.fixture
async def db_client(db_session: AsyncSession) -> AsyncSession:
    """Override get_uow with a UoW bound to the savepoint-scoped db_session
    and yield that same session for the test body to seed/read rows with.

    Replaces the old per-test in-memory embedded-DB engine: this fixture gives
    each test an isolated, empty-enough view of PostgreSQL (via db_session's
    savepoint rollback) while letting HTTP requests through the app under
    test and direct row seeding both see each other's writes, since they
    share the same underlying connection/transaction.
    """
    from app.dependencies import get_uow
    from app.main import app

    async def _override():
        async with DbSessionUnitOfWork(db_session) as uow:
            yield uow

    app.dependency_overrides[get_uow] = _override
    yield db_session


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
                bind=conn,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            session = session_factory()

            yield session

            await session.close()
            if nested.is_active:
                await nested.rollback()
            await trans.rollback()
    finally:
        await engine.dispose()
