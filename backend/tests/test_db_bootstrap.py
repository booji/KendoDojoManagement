"""Integration tests for app.db.bootstrap (issue #250, updated for #264).

These exercise real PostgreSQL behaviour (existence of the alembic_version
table, real `alembic upgrade head` / `Base.metadata.create_all` execution)
that a StubRepository cannot express, so they run against the real test
Postgres server rather than using in-memory stubs.

Issue #264 gave the Alembic chain a baseline migration and made
`prepare_database` run `alembic upgrade head` unconditionally — it no longer
branches on fresh-vs-existing, so the private `_create_schema` / `_stamp_head`
helpers these tests used to monkeypatch and assert call-order against no
longer exist (see test_migrations.py::test_bootstrap_no_longer_branches_on_fresh_vs_existing,
which asserts exactly that). The tests below were updated to assert on
outcomes instead of internal call sequencing, and two new tests document the
real behaviour change: a legacy pre-Alembic database (tables built by
`create_all`, no `alembic_version` table at all) is no longer auto-detected
and silently upgraded.
  - If its schema is current (matches today's ORM), the fix is a one-time
    manual `alembic stamp head` — see
    `test_legacy_database_at_current_schema_needs_stamp_head`.
  - If its schema is stale (predates migrations that shipped after it was
    last redeployed), there is no single correct stamp target at all —
    `test_stale_legacy_database_stamped_at_head_stays_missing_later_tables`
    documents that failure mode rather than papering over it.
Both are documented in the baseline migration's docstring and
docs/install/upgrading.md.

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

import asyncio
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
# Criterion 1: empty database -> alembic upgrade head reaches head
# ---------------------------------------------------------------------------


async def test_fresh_database_reaches_head_via_migrations(
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
# Criterion 2: already at head -> running prepare_database again is a no-op
# ---------------------------------------------------------------------------


async def test_database_already_at_head_stays_at_head(
    _bootstrap_db: str,
) -> None:
    from app.db.bootstrap import prepare_database

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

    # prepare_database no longer branches on fresh-vs-existing (#264) — this
    # just runs `alembic upgrade head` again, which alembic treats as a no-op
    # once the recorded revision already is head.
    await prepare_database(_bootstrap_db)

    assert await _alembic_version(_bootstrap_db) == _expected_head_revision()


def _run_alembic(database_url: str, action, *args) -> None:
    """Run a blocking alembic `command.*` call against `database_url` off-thread.

    alembic's env.py drives its own `asyncio.run(...)`, which cannot nest
    inside a test's already-running event loop — every direct `command.*`
    call in this module goes through this helper for that reason (mirrors
    app.db.bootstrap's own `_run_alembic_upgrade`).
    """
    import os

    from app.db.bootstrap import _alembic_config

    cfg = _alembic_config(database_url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        action(cfg, *args)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


# ---------------------------------------------------------------------------
# Criterion 3 (behaviour changed by #264): a legacy pre-Alembic database
# (tables exist, no alembic_version at all) is no longer auto-detected and
# silently upgraded. prepare_database now always runs `alembic upgrade head`
# unconditionally, which for this state means replaying the baseline
# migration's CREATE TABLE statements against tables that already exist —
# it must fail loudly rather than silently doing the wrong thing. The
# documented fix (docs/install/upgrading.md, the baseline migration's docstring) is
# `alembic stamp head` — correct precisely when the legacy schema already
# matches the current ORM, which is what this test builds (a full
# `Base.metadata.create_all` of today's models — proven identical to a fully
# migrated database by test_migrated_schema_matches_orm_metadata_exactly).
# ---------------------------------------------------------------------------


async def test_legacy_database_at_current_schema_needs_stamp_head(
    _bootstrap_db: str,
) -> None:
    from alembic import command
    from app.db.bootstrap import _upgrade_head, prepare_database

    # Legacy pre-alembic deploy whose schema has been kept current: tables
    # built by today's Base.metadata.create_all, no alembic_version at all.
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

    # Unconditional `alembic upgrade head` fails loudly (tries to replay the
    # baseline's CREATE TABLE statements against tables that already exist)
    # rather than silently doing the wrong thing.
    with pytest.raises(Exception):
        await prepare_database(_bootstrap_db)

    # The fix: stamp head (not a1b2c3d4e5f6, not the new baseline — both
    # would leave alembic_version naming a revision *before* tables this
    # create_all already built, and the next upgrade would try to recreate
    # them). Safe here because the schema already matches the ORM at head.
    await asyncio.to_thread(_run_alembic, _bootstrap_db, command.stamp, "head")
    await _upgrade_head(_bootstrap_db)  # no-op: already at head

    assert await _alembic_version(_bootstrap_db) == _expected_head_revision()


# ---------------------------------------------------------------------------
# Criterion 3b: a legacy database that is genuinely stale — its create_all
# schema predates migrations that shipped after it — has NO single correct
# stamp target. This test documents (does not "fix") that failure mode:
# stamping head against a stale schema does not error, but silently leaves
# the database missing tables/columns those later migrations would have
# added. This is exactly why docs/install/upgrading.md tells an operator who is not
# sure their schema is current to diff it against the ORM first rather than
# guess a stamp point.
# ---------------------------------------------------------------------------


async def test_stale_legacy_database_stamped_at_head_stays_missing_later_tables(
    _bootstrap_db: str,
) -> None:
    from alembic import command

    # A stale legacy deploy: schema only as of the pre-baseline point (i.e.
    # predates federations/member_federations/invites and everything added
    # after them — reached here by running the chain up to the baseline
    # itself, then dropping the alembic_version row it creates so the
    # database looks exactly like a legacy create_all deploy with no version
    # record, just an older one than the previous test's).
    await asyncio.to_thread(
        _run_alembic, _bootstrap_db, command.upgrade, "000000000000"
    )
    engine = create_async_engine(_bootstrap_db)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE alembic_version"))
    finally:
        await engine.dispose()

    assert "federations" not in await _table_names(_bootstrap_db)

    # Blindly following the common-case advice ("stamp head") on this stale
    # database does not raise — it just marks everything as done...
    await asyncio.to_thread(_run_alembic, _bootstrap_db, command.stamp, "head")
    assert await _alembic_version(_bootstrap_db) == _expected_head_revision()

    # ...leaving tables that real migrations after the baseline would have
    # created permanently missing, silently. There is no stamp target that
    # avoids this for a genuinely stale schema — see docs/install/upgrading.md.
    assert "federations" not in await _table_names(_bootstrap_db)
    assert "member_federations" not in await _table_names(_bootstrap_db)
    assert "invites" not in await _table_names(_bootstrap_db)


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
