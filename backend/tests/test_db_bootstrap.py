"""Integration tests for app.db.bootstrap (issue #250).

These exercise real PostgreSQL behaviour (existence of the alembic_version
table, real `alembic upgrade head` / `Base.metadata.create_all` execution)
that a StubRepository cannot express, so they run against the real test
Postgres server rather than using in-memory stubs.

Test isolation strategy
------------------------
Each test gets its own **throwaway physical database** on the same Postgres
server used by the rest of the suite (not just a schema within the shared
`kendo_test` database). This is deliberate: the shared `kendo_test` database
already has the full ORM schema created by the session-scoped `_setup_schema`
autouse fixture in conftest.py (and no `alembic_version` table), which is
itself one of the exact states these tests need to construct and control
independently. Reusing/mutating that shared database directly would race
every other test module.

The `kendo_test` Postgres role is the server's initdb superuser role (see
docker-compose.test.yml / .env.test), so it has CREATEDB. The `_bootstrap_db`
fixture connects with AUTOCOMMIT isolation, issues `CREATE DATABASE`, yields
a full asyncpg URL pointing at the new database, then on teardown terminates
any lingering backends and `DROP DATABASE ... WITH (FORCE)`. Nothing here
ever touches the shared `kendo_test` database's tables.

No Playwright/e2e tests are included for this issue: it is a startup/
infrastructure concern (what entrypoint.sh does before uvicorn ever binds a
port) with no UI surface for a browser to observe.
"""

import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import _DATABASE_URL


def _admin_url() -> str:
    """The shared test server URL, used only to CREATE/DROP throwaway databases."""
    return _DATABASE_URL


def _url_for_db(name: str) -> str:
    base, _, _ = _DATABASE_URL.rpartition("/")
    return f"{base}/{name}"


@pytest.fixture
async def _bootstrap_db():
    """Create a throwaway Postgres database for one test, then drop it.

    Yields a postgresql+asyncpg:// URL pointing at an EMPTY database (no
    tables, no alembic_version) — the true "fresh volume" starting state.
    """
    db_name = f"kendo_test_bootstrap_{uuid.uuid4().hex[:12]}"
    admin_engine = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await admin_engine.dispose()

    try:
        yield _url_for_db(db_name)
    finally:
        admin_engine = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        try:
            async with admin_engine.connect() as conn:
                await conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :name AND pid <> pg_backend_pid()"
                    ),
                    {"name": db_name},
                )
                await conn.execute(
                    text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
                )
        finally:
            await admin_engine.dispose()


async def _table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    finally:
        await engine.dispose()


async def _alembic_version(database_url: str) -> str | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda c: inspect(c).get_table_names())
            if "alembic_version" not in names:
                return None
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
            return row[0] if row else None
    finally:
        await engine.dispose()


def _expected_head_revision() -> str:
    import os

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    script = ScriptDirectory.from_config(cfg)
    return script.get_current_head()


# ---------------------------------------------------------------------------
# Criterion 1: empty public schema -> create_all + stamp head
# ---------------------------------------------------------------------------


async def test_fresh_database_creates_schema_and_stamps_head(
    _bootstrap_db: str,
) -> None:
    from app.db.bootstrap import prepare_database

    assert await _table_names(_bootstrap_db) == set()

    await prepare_database(_bootstrap_db)

    tables = await _table_names(_bootstrap_db)
    assert "alembic_version" in tables
    assert "members" in tables
    assert "sessions" in tables or "session_instances" in tables
    assert "users" in tables

    assert await _alembic_version(_bootstrap_db) == _expected_head_revision()


# ---------------------------------------------------------------------------
# Criterion 2: alembic_version already present -> upgrade path only
# ---------------------------------------------------------------------------


async def test_existing_database_takes_upgrade_path_not_create_all(
    _bootstrap_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.db.bootstrap as bootstrap

    # Simulate an already-bootstrapped instance: full schema + alembic_version
    # at head, exactly what a second boot of an already-running deployment
    # looks like.
    engine = create_async_engine(_bootstrap_db)
    try:
        import app.attendance.db_models  # noqa: F401
        import app.auth.db_models  # noqa: F401
        import app.federations.db_models  # noqa: F401
        import app.grades.db_models  # noqa: F401
        import app.member_federations.db_models  # noqa: F401
        import app.members.db_models  # noqa: F401
        import app.sessions.db_models  # noqa: F401
        import app.settings.models  # noqa: F401
        from app.db.base import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32))")
            )
            await conn.execute(
                text("INSERT INTO alembic_version VALUES (:rev)"),
                {"rev": _expected_head_revision()},
            )
    finally:
        await engine.dispose()

    calls: list[str] = []

    async def fake_create_schema(_engine) -> None:
        calls.append("create_schema")

    async def fake_stamp_head(_url) -> None:
        calls.append("stamp_head")

    async def fake_upgrade_head(_url) -> None:
        calls.append("upgrade_head")

    monkeypatch.setattr(bootstrap, "_create_schema", fake_create_schema)
    monkeypatch.setattr(bootstrap, "_stamp_head", fake_stamp_head)
    monkeypatch.setattr(bootstrap, "_upgrade_head", fake_upgrade_head)

    await bootstrap.prepare_database(_bootstrap_db)

    assert calls == ["upgrade_head"]


# ---------------------------------------------------------------------------
# Criterion 3: tables exist but no alembic_version -> NOT treated as fresh
# ---------------------------------------------------------------------------


async def test_legacy_database_without_alembic_version_takes_upgrade_path(
    _bootstrap_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.db.bootstrap as bootstrap

    # Legacy pre-alembic deploy: application tables exist (created by the old
    # create_all-in-lifespan path) but there has never been an alembic_version
    # table. Silently taking the fresh-database shortcut here would stamp head
    # without ever checking the real schema matches — exactly what criterion 3
    # forbids.
    engine = create_async_engine(_bootstrap_db)
    try:
        import app.attendance.db_models  # noqa: F401
        import app.auth.db_models  # noqa: F401
        import app.federations.db_models  # noqa: F401
        import app.grades.db_models  # noqa: F401
        import app.member_federations.db_models  # noqa: F401
        import app.members.db_models  # noqa: F401
        import app.sessions.db_models  # noqa: F401
        import app.settings.models  # noqa: F401
        from app.db.base import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

    assert "alembic_version" not in await _table_names(_bootstrap_db)

    calls: list[str] = []

    async def fake_create_schema(_engine) -> None:
        calls.append("create_schema")

    async def fake_stamp_head(_url) -> None:
        calls.append("stamp_head")

    async def fake_upgrade_head(_url) -> None:
        calls.append("upgrade_head")

    monkeypatch.setattr(bootstrap, "_create_schema", fake_create_schema)
    monkeypatch.setattr(bootstrap, "_stamp_head", fake_stamp_head)
    monkeypatch.setattr(bootstrap, "_upgrade_head", fake_upgrade_head)

    await bootstrap.prepare_database(_bootstrap_db)

    assert calls == ["upgrade_head"]


# ---------------------------------------------------------------------------
# Criterion 4: running bootstrap twice is safe/idempotent
# ---------------------------------------------------------------------------


async def test_bootstrap_twice_is_idempotent(_bootstrap_db: str) -> None:
    from app.db.bootstrap import prepare_database

    await prepare_database(_bootstrap_db)
    first_tables = await _table_names(_bootstrap_db)
    first_version = await _alembic_version(_bootstrap_db)

    # Second run must take the "existing" branch and land at the same state.
    await prepare_database(_bootstrap_db)

    assert await _table_names(_bootstrap_db) == first_tables
    assert (
        await _alembic_version(_bootstrap_db)
        == first_version
        == _expected_head_revision()
    )


# ---------------------------------------------------------------------------
# Criterion 5: resilient to the DB not being ready yet — retries, not crash
# ---------------------------------------------------------------------------


async def test_prepare_database_retries_on_connection_failure() -> None:
    import time

    from app.db.bootstrap import prepare_database

    # Port 1 is not a listening Postgres server; every connection attempt
    # fails immediately, so this isolates the retry/backoff behaviour without
    # depending on a real outage.
    unreachable_url = (
        "postgresql+asyncpg://kendo_test:kendo_test_password@localhost:1/kendo_test"
    )

    start = time.monotonic()
    with pytest.raises(Exception):
        await prepare_database(unreachable_url, max_attempts=3, initial_delay=0.05)
    elapsed = time.monotonic() - start

    # A crash-immediately implementation would fail in well under one retry
    # delay. Three attempts with backoff starting at 0.05s must take at least
    # the two inter-attempt waits.
    assert elapsed >= 0.09
