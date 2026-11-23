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
Both are documented in the baseline migration's docstring.

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
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import _DATABASE_URL
from tests.migration_support import APP_USER as _APP_USER
from tests.migration_support import app_url as _app_url


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

    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))

    tables = await _table_names(_bootstrap_db)
    assert "alembic_version" in tables
    assert "members" in tables
    assert "sessions" in tables or "session_instances" in tables
    assert "accounts" in tables

    assert await _alembic_version(_bootstrap_db) == _expected_head_revision()


async def test_fresh_database_holds_every_fik_affiliate(_bootstrap_db: str) -> None:
    """#613: the bundled FIK list is synced in, with no Admin action, and a
    second run changes nothing."""
    from app.db.bootstrap import prepare_database
    from app.federations.fik_catalogue import load

    async def catalogue() -> set[tuple]:
        engine = create_async_engine(_bootstrap_db, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT id, source_key, name, website, is_active "
                        "FROM federations WHERE source = 'fik'"
                    )
                )
                return set(result.all())
        finally:
            await engine.dispose()

    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))
    first = await catalogue()
    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))

    assert {row[1] for row in first} == {r["source_key"] for r in load()}
    assert all(row[4] for row in first)
    assert await catalogue() == first


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
    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))

    assert await _alembic_version(_bootstrap_db) == _expected_head_revision()


def _run_alembic(database_url: str, action, *args) -> None:
    """Run a blocking alembic `command.*` call against `database_url` off-thread.

    alembic's env.py drives its own `asyncio.run(...)`, which cannot nest
    inside a test's already-running event loop — every direct `command.*`
    call in this module goes through this helper for that reason (mirrors
    app.db.bootstrap's own `_run_alembic_upgrade`).
    """
    from app.db.bootstrap import _alembic_config

    action(_alembic_config(database_url), *args)


# ---------------------------------------------------------------------------
# Criterion 3 (behaviour changed by #264): a legacy pre-Alembic database
# (tables exist, no alembic_version at all) is no longer auto-detected and
# silently upgraded. prepare_database now always runs `alembic upgrade head`
# unconditionally, which for this state means replaying the baseline
# migration's CREATE TABLE statements against tables that already exist —
# it must fail loudly rather than silently doing the wrong thing. The
# documented fix (the baseline migration's docstring) is
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
        await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))

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
# added. This is exactly why the baseline migration's docstring tells an
# operator who is not sure their schema is current to diff it against the ORM
# first rather than guess a stamp point.
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
    # avoids this for a genuinely stale schema — see the baseline migration's
    # docstring.
    assert "federations" not in await _table_names(_bootstrap_db)
    assert "member_federations" not in await _table_names(_bootstrap_db)
    assert "invites" not in await _table_names(_bootstrap_db)


# ---------------------------------------------------------------------------
# Criterion 4: running bootstrap twice is safe/idempotent
# ---------------------------------------------------------------------------


async def test_bootstrap_twice_is_idempotent(_bootstrap_db: str) -> None:
    from app.db.bootstrap import prepare_database

    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))
    first_tables = await _table_names(_bootstrap_db)
    first_version = await _alembic_version(_bootstrap_db)

    # Second run must take the "existing" branch and land at the same state.
    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))

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
        await prepare_database(
            unreachable_url,
            _app_url(unreachable_url),
            max_attempts=3,
            initial_delay=0.05,
        )
    elapsed = time.monotonic() - start

    # A crash-immediately implementation would fail in well under one retry
    # delay. Three attempts with backoff starting at 0.05s must take at least
    # the two inter-attempt waits.
    assert elapsed >= 0.09


# ---------------------------------------------------------------------------
# #453: bootstrap creates the least-privilege app user (ADR-0007)
# ---------------------------------------------------------------------------


async def test_bootstrap_leaves_app_user_with_row_privileges_only(
    _bootstrap_db: str,
) -> None:
    from app.db.bootstrap import prepare_database

    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))

    engine = create_async_engine(_app_url(_bootstrap_db), poolclass=NullPool)
    try:
        async with engine.connect() as conn:

            async def scalar(sql: str):
                return (await conn.execute(text(sql))).scalar()

            assert await scalar("SELECT current_setting('is_superuser')") == "off"
            assert (
                await scalar("SELECT has_schema_privilege('public', 'CREATE')") is False
            )
            # PostgreSQL grants TEMP to PUBLIC on every new database (#482).
            assert (
                await scalar(
                    "SELECT has_database_privilege(current_database(), 'TEMP')"
                )
                is False
            )
            extra = (
                await conn.execute(
                    text(
                        "SELECT c.relname, p FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace, "
                        "unnest(ARRAY['TRUNCATE', 'TRIGGER', 'REFERENCES']) p "
                        "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                        "AND has_table_privilege(c.oid, p)"
                    )
                )
            ).all()
            assert extra == []
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert await scalar(
                    f"SELECT has_table_privilege('members', '{privilege}')"
                ), privilege
                assert await scalar(
                    f"SELECT has_table_privilege('alembic_version', '{privilege}')"
                ) is (privilege == "SELECT"), privilege
    finally:
        await engine.dispose()


# Port 1: nothing listens there, so a refusal that came after connecting would
# surface as a connection error rather than the refusal under test.
_NOWHERE = "postgresql+asyncpg://kendo_test:kendo_test_password@localhost:1/kendo_test"


@pytest.mark.parametrize("name", ['kendo"; DROP ROLE kendo_test; --', "kendo-app"])
async def test_bootstrap_refuses_an_unsafe_app_user_name(name: str) -> None:
    from app.db.bootstrap import prepare_database

    with pytest.raises(ValueError, match="unsafe"):
        await prepare_database(_NOWHERE, _app_url(_NOWHERE, user=name))


async def test_bootstrap_refuses_an_app_user_equal_to_the_migration_user() -> None:
    from app.db.bootstrap import prepare_database

    with pytest.raises(RuntimeError, match="MIGRATION_DATABASE_URL"):
        await prepare_database(_NOWHERE, _NOWHERE)


async def _as_app_user(app_url: str, sql: str):
    engine = create_async_engine(app_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql))).scalar()
    finally:
        await engine.dispose()


async def test_rerunning_bootstrap_rotates_the_app_user_password(
    _bootstrap_db: str,
) -> None:
    from app.db.bootstrap import prepare_database

    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))
    rotated = _app_url(_bootstrap_db, password="rotated-password")
    await prepare_database(_bootstrap_db, rotated)

    assert await _as_app_user(rotated, "SELECT current_user") == _APP_USER


async def test_tables_created_after_bootstrap_get_row_privileges_only(
    _bootstrap_db: str,
) -> None:
    from app.db.bootstrap import prepare_database

    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))
    # What a later migration does, as the migration user, before the next
    # bootstrap has had a chance to re-grant anything.
    engine = create_async_engine(_bootstrap_db)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE later_table (id serial)"))
    finally:
        await engine.dispose()

    app_url = _app_url(_bootstrap_db)
    assert (
        await _as_app_user(
            app_url, "INSERT INTO later_table DEFAULT VALUES RETURNING id"
        )
        == 1
    )
    assert (
        await _as_app_user(
            app_url, "SELECT has_table_privilege('later_table', 'TRUNCATE')"
        )
        is False
    )


async def test_app_startup_refuses_a_superuser_connection(_bootstrap_db: str) -> None:
    from app.db.bootstrap import prepare_database
    from app.main import _refuse_superuser

    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))

    for url, refused in ((_bootstrap_db, True), (_app_url(_bootstrap_db), False)):
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                if refused:
                    with pytest.raises(RuntimeError, match="MIGRATION_DATABASE_URL"):
                        await _refuse_superuser(conn)
                else:
                    await _refuse_superuser(conn)
        finally:
            await engine.dispose()


async def test_bootstrap_refuses_to_demote_an_existing_superuser(
    _bootstrap_db: str,
) -> None:
    from app.db.bootstrap import prepare_database

    other = "kendo_test_other_superuser"
    engine = create_async_engine(_bootstrap_db, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            # Roles outlive the database; a run killed mid-test leaves one.
            await conn.execute(text(f'DROP ROLE IF EXISTS "{other}"'))
            await conn.execute(text(f'CREATE ROLE "{other}" SUPERUSER'))
        try:
            with pytest.raises(RuntimeError, match="superuser"):
                await prepare_database(_bootstrap_db, _app_url(_bootstrap_db, other))
            async with engine.connect() as conn:
                still_super = await conn.execute(
                    text("SELECT rolsuper FROM pg_roles WHERE rolname = :r"),
                    {"r": other},
                )
                assert still_super.scalar() is True
        finally:
            async with engine.connect() as conn:
                await conn.execute(text(f'DROP ROLE IF EXISTS "{other}"'))
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# #606: the migration unit says in the journal what it did
# ---------------------------------------------------------------------------


def _run_migration_unit(database_url: str) -> str:
    """Run the migration unit as kendo-migrate does; return what it printed."""
    env = {
        **os.environ,
        "MIGRATION_DATABASE_URL": database_url,
        "DATABASE_URL": _app_url(database_url),
    }
    result = subprocess.run(
        [sys.executable, "-m", "app.db.bootstrap"],
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout + result.stderr


async def test_migration_unit_logs_each_revision_it_applies(
    _bootstrap_db: str,
) -> None:
    head = _expected_head_revision()

    output = await asyncio.to_thread(_run_migration_unit, _bootstrap_db)

    assert "Schema at revision none, upgrading to head" in output
    assert "Running upgrade  -> 000000000000" in output
    assert f"-> {head}" in output
    assert f"Schema now at head {head}" in output


async def test_migration_unit_at_head_says_so(_bootstrap_db: str) -> None:
    head = _expected_head_revision()
    await asyncio.to_thread(_run_migration_unit, _bootstrap_db)

    output = await asyncio.to_thread(_run_migration_unit, _bootstrap_db)

    assert f"Schema at revision {head}, upgrading to head" in output
    assert "Running upgrade" not in output
    assert f"Schema already at head {head}" in output


async def test_migrating_in_process_leaves_the_app_loggers_enabled(
    _bootstrap_db: str,
) -> None:
    """The fix must not be fileConfig, which disables loggers it doesn't know."""
    import logging

    import app.core.middleware  # noqa: F401
    import app.core.security_logger  # noqa: F401
    from app.db.bootstrap import prepare_database

    await prepare_database(_bootstrap_db, _app_url(_bootstrap_db))

    for name in ("security_events", "app.core.middleware"):
        assert logging.getLogger(name).disabled is False, name


async def test_a_schema_at_several_heads_logs_every_one(
    _bootstrap_db: str, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """Merged branches leave alembic_version one row per head: the log names
    them all, in a stable order, and "already at head" compares them as a set
    (#606). The upgrade itself is stubbed: no shipped chain branches."""
    import logging

    from app.db import bootstrap

    engine = create_async_engine(_bootstrap_db, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"
                )
            )
            await conn.execute(
                text("INSERT INTO alembic_version VALUES ('bbbb'), ('aaaa')")
            )
    finally:
        await engine.dispose()
    monkeypatch.setattr(bootstrap, "_run_alembic_upgrade", lambda url: None)

    with caplog.at_level(logging.INFO, logger="app.db.bootstrap"):
        await bootstrap._upgrade_head(_bootstrap_db)

    assert "Schema at revision aaaa, bbbb, upgrading to head" in caplog.text
    assert "Schema already at head aaaa, bbbb" in caplog.text
