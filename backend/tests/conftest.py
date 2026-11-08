import asyncio
import os
from contextlib import nullcontext

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Must be set before any app imports: config reads it at import time, and
# the decoy-id HMAC in webauthn_ceremony.py is keyed with it
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
    """Build a session cookie the real guard accepts for the given claims.

    Use this for any test asserting an *authorization* outcome. Overriding the
    guard under test (e.g. ``dependency_overrides[REQUIRE_ADMIN] = a member
    stub``) replaces the code that produces the 403, so the assertion ends up
    exercising whatever redundant role check happens to sit inside the route
    instead — such a test passes even if the route's guard is removed. Handing
    the real guard a real Auth Session keeps the check honest.

    No DB is involved: see ``tests.auth_support.sign_in``.
    """
    from app.auth.models import AccountClaims
    from tests.auth_support import sign_in

    def _make(claims: "AccountClaims") -> dict[str, str]:
        return {"access_token": sign_in(claims)}

    return _make


@pytest.fixture()
def security_events_to_caplog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let caplog see security events.

    caplog listens on the root logger, which production cuts the
    security_events logger off from (#461). Use with
    ``pytestmark = pytest.mark.usefixtures("security_events_to_caplog")``.
    """
    import logging

    monkeypatch.setattr(logging.getLogger("security_events"), "propagate", True)


@pytest.fixture(autouse=True)
def _default_attendance_repo():
    """Install an empty attendance fake so tests that don't wire one don't hit the DB.

    Individual tests can override get_attendance_repo after this fixture runs.
    """
    from app.attendance.dependencies import get_attendance_repo
    from app.main import app
    from tests.fake_repositories import InMemoryAttendanceRepository

    repo = InMemoryAttendanceRepository()
    app.dependency_overrides.setdefault(get_attendance_repo, lambda: repo)
    yield
    # Teardown is handled by each test file's own clear_overrides fixture.


@pytest.fixture(autouse=True)
def _default_current_member_id():
    """Give every authenticated caller a Member id derived from their user id.

    Attendance is keyed by Member id (#340), so the check-in routes and
    GET /sessions resolve the caller's user id to their member record. Without
    a default, every stub-based test of those routes would fall through to the
    real SqlMemberRepository and hit the database.

    The mapping is synthetic but faithful in the ways tests depend on: each
    user gets one stable member id, and different users get different ones. A
    test that needs a specific member id -- or the "user with no member
    record" case -- overrides get_current_member_id itself.
    """
    from typing import Annotated

    from fastapi import Depends

    from app.auth.guards import REQUIRE_MEMBER
    from app.auth.models import AccountClaims
    from app.main import app
    from app.members.dependencies import get_current_member_id

    async def _member_id_for_caller(
        claims: Annotated[AccountClaims, Depends(REQUIRE_MEMBER)],
    ) -> str:
        return f"member-of-{claims.sub}"

    app.dependency_overrides.setdefault(get_current_member_id, _member_id_for_caller)
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


@pytest.fixture(autouse=True)
def _test_auth_off_for_startup_validation(monkeypatch: pytest.MonkeyPatch):
    """.env.test sets ALLOW_TEST_AUTH=true so the suite can sign in through
    POST /auth/login/test, and validate_startup_config() refuses that in
    production (#590). Every test that drives the production path would then
    fail on it instead of on what it checks. The route was registered at
    import, so turning the flag off here leaves it in place; a test of the
    refusal sets it back itself."""
    import app.config as config

    monkeypatch.setattr(config, "ALLOW_TEST_AUTH", False)


def _e2e_cleanup(request: pytest.FixtureRequest):
    """e2e tests write through the live server, which commits for real: remove
    the Members and Accounts they created (#568). Other tests roll back."""
    if not request.path.name.startswith("test_e2e_"):
        return nullcontext()
    from tests.e2e_support import leaves_members_as_found

    return leaves_members_as_found()


@pytest.fixture(scope="module", autouse=True)
def _e2e_module_cleanup(request: pytest.FixtureRequest):
    """For module-scoped fixtures that sign someone in."""
    with _e2e_cleanup(request):
        yield


@pytest.fixture(autouse=True)
def _e2e_test_cleanup(request: pytest.FixtureRequest):
    with _e2e_cleanup(request):
        yield


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

    run_tests.sh creates a fresh per-run database, runs `alembic upgrade
    head` against it via `python -m app.db.bootstrap`, and only then starts
    uvicorn — the script is the sole schema owner here (the app process
    stopped migrating in #391) (see the module docstring in test_conftest_schema_ownership.py for
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


@pytest_asyncio.fixture
async def scratch_db() -> str:
    """URL of a fresh, empty, throwaway database, dropped on teardown.

    For tests that drive alembic themselves (see tests/migration_support.py):
    migrating the shared test database would race the rest of the suite.
    """
    import uuid

    from app.db.scratch import create_database, drop_database, url_parts

    base_url, _ = url_parts(_DATABASE_URL)
    name = f"kendo_test_mig_{uuid.uuid4().hex[:12]}"
    url = await create_database(base_url, name)
    try:
        yield url
    finally:
        await drop_database(base_url, name)
