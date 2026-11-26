"""Tests for issue #264 — Alembic as the single source of truth for schema.

These are Tier 2 (PostgreSQL-backed) tests: each test spins up its own
throwaway scratch database (created via a connection to the `postgres`
maintenance database) rather than using the shared `kendo_test` database that
the rest of the suite shares — running `alembic upgrade head` /
`create_all` / `drop_all` repeatedly against the shared database would race
with other tests and violate the "name must contain 'test'" guard's intent
(that guard exists so `drop_all` can't hit a non-test DB by accident; these
scratch DBs are still test databases, just per-test ones).

No Playwright / `test_e2e_*` stubs are included for this issue. Every
acceptance criterion here is about database schema state and process startup
sequencing (`alembic upgrade head` from empty, from a legacy `create_all`
deploy, schema-diff parity, and `bootstrap.prepare_database` behaviour) —
none of it is observable through a browser. Writing browser stubs would fake
coverage rather than provide it.
"""

import asyncio
import os
import uuid

import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db.scratch import create_database, drop_database, url_parts
from tests.migration_support import app_url

_DATABASE_URL = os.environ["DATABASE_URL"]
_BASE_URL, _ = url_parts(_DATABASE_URL)


def _scratch_db_name() -> str:
    return f"kendo_test_mig_{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def scratch_db_url():
    """Yield the SQLAlchemy URL of a fresh, empty, throwaway database."""
    db_name = _scratch_db_name()
    url = await create_database(_BASE_URL, db_name)
    try:
        yield url
    finally:
        await drop_database(_BASE_URL, db_name)


def _import_all_models():
    """Import every model module so its tables register on Base.metadata.

    Mirrors the exact import list in app.db.bootstrap._create_schema /
    tests/conftest.py's _setup_schema fixture.
    """
    import app.attendance.db_models  # noqa: F401
    import app.auth.db_models  # noqa: F401
    import app.federations.db_models  # noqa: F401
    import app.grades.db_models  # noqa: F401
    import app.member_federations.db_models  # noqa: F401
    import app.members.db_models  # noqa: F401
    import app.sessions.db_models  # noqa: F401
    import app.settings.models  # noqa: F401
    from app.db.base import Base

    return Base


def _alembic_config(database_url: str):
    """Mirror app.db.bootstrap._alembic_config exactly (see that module for
    why config_file_name is left unset)."""
    from alembic.config import Config

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    cfg.set_main_option("version_path_separator", "os")
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _run_alembic_upgrade_head(database_url: str) -> None:
    """Blocking. Run via asyncio.to_thread — env.py drives its own asyncio.run()
    and cannot be nested inside a running event loop."""
    from alembic import command

    cfg = _alembic_config(database_url)
    command.upgrade(cfg, "head")


def _run_alembic_stamp_head(database_url: str) -> None:
    from alembic import command

    cfg = _alembic_config(database_url)
    command.stamp(cfg, "head")


def _current_head_revision() -> str:
    from alembic.script import ScriptDirectory

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = ScriptDirectory(os.path.join(backend_dir, "alembic"))
    return script.get_current_head()


async def _alembic_version(engine) -> str | None:
    async with engine.connect() as conn:
        table_names = await conn.run_sync(lambda c: inspect(c).get_table_names())
        if "alembic_version" not in table_names:
            return None
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        row = result.first()
        return row[0] if row else None


# ---------------------------------------------------------------------------
# AC1 — `alembic upgrade head` against a completely empty database reaches
# head and produces the full schema (i.e. a baseline/revision-zero exists).
# ---------------------------------------------------------------------------


async def test_alembic_upgrade_head_from_empty_database_reaches_head(
    scratch_db_url: str,
):
    await asyncio.to_thread(_run_alembic_upgrade_head, scratch_db_url)

    engine = create_async_engine(scratch_db_url, poolclass=NullPool)
    try:
        version = await _alembic_version(engine)
        assert version == _current_head_revision()

        async with engine.connect() as conn:
            table_names = await conn.run_sync(lambda c: inspect(c).get_table_names())
        # Tables that only exist because the baseline migration created them —
        # today's chain assumes these already exist and only ALTERs them.
        # NB: there is no `sessions` table — session rows live in
        # `session_instances` (see app.sessions.db_models). The name in issue
        # #264's prose is informal shorthand, not a real table.
        for expected in ("members", "session_instances", "accounts", "federations"):
            assert expected in table_names, (
                f"expected table {expected!r} to exist after alembic upgrade "
                f"head from empty; got tables: {sorted(table_names)}"
            )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# AC2 — an existing populated database (schema built by create_all, stamped
# at current head — simulating a legacy pre-baseline deploy) still migrates
# forward with no data loss and without re-running the baseline.
# ---------------------------------------------------------------------------


async def test_alembic_upgrade_head_on_legacy_stamped_database_preserves_data(
    scratch_db_url: str,
):
    Base = _import_all_models()

    engine = create_async_engine(scratch_db_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Simulate the legacy bootstrap path: schema built via create_all,
        # then stamped at whatever alembic currently considers head (this is
        # exactly what app.db.bootstrap._stamp_head does today on a "fresh"
        # database, and it's the state every already-deployed instance is in).
        await asyncio.to_thread(_run_alembic_stamp_head, scratch_db_url)

        # Insert a row a real deploy would have accumulated over time.
        federation_id = str(uuid.uuid4())
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO federations (id, name, is_pinned, is_active) "
                    "VALUES (:id, :name, false, true)"
                ),
                {"id": federation_id, "name": "All Japan Kendo Federation"},
            )

        # Forward migration must succeed without re-running the baseline
        # (which would fail trying to CREATE TABLE federations again, since
        # it already exists) and must not touch existing data.
        await asyncio.to_thread(_run_alembic_upgrade_head, scratch_db_url)

        version = await _alembic_version(engine)
        assert version == _current_head_revision()

        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM federations WHERE id = :id"),
                {"id": federation_id},
            )
            row = result.first()
        assert row is not None, "existing row lost across migration"
        assert row[0] == "All Japan Kendo Federation"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# AC3 — the schema produced by running migrations is identical to the schema
# produced by Base.metadata.create_all. This is the most valuable test: a
# non-empty autogenerate diff means the two schema sources have drifted.
# ---------------------------------------------------------------------------


async def test_migrated_schema_matches_orm_metadata_exactly(scratch_db_url: str):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    Base = _import_all_models()

    await asyncio.to_thread(_run_alembic_upgrade_head, scratch_db_url)

    engine = create_async_engine(scratch_db_url, poolclass=NullPool)
    try:

        def _diff(sync_conn):
            ctx = MigrationContext.configure(sync_conn)
            return compare_metadata(ctx, Base.metadata)

        async with engine.connect() as conn:
            diff = await conn.run_sync(_diff)
    finally:
        await engine.dispose()

    # alembic_version is created by alembic itself, not by the ORM, and is
    # expected to show up as a spurious "remove_table" entry — filter it out.
    def _is_spurious_alembic_version_entry(entry) -> bool:
        # compare_metadata entries are tuples like
        # ("remove_table", Table(...)) or ("remove_index", Index(...)) etc.
        target = entry[1] if len(entry) > 1 else None
        table = getattr(target, "table", target)
        table_name = getattr(table, "name", None)
        return table_name == "alembic_version"

    meaningful_diff = [
        entry for entry in diff if not _is_spurious_alembic_version_entry(entry)
    ]

    assert meaningful_diff == [], (
        "alembic migration chain and Base.metadata have drifted — "
        f"autogenerate diff is non-empty: {meaningful_diff!r}"
    )


# ---------------------------------------------------------------------------
# AC4 — bootstrap.prepare_database no longer branches on fresh-vs-existing:
# it produces the same, fully-migrated schema whether the target database
# started empty or already populated (via legacy create_all + stamp).
# ---------------------------------------------------------------------------


async def test_prepare_database_produces_head_schema_from_empty_database(
    scratch_db_url: str,
):
    from app.db.bootstrap import prepare_database

    await prepare_database(
        scratch_db_url, app_url(scratch_db_url), max_attempts=1, initial_delay=0.01
    )

    engine = create_async_engine(scratch_db_url, poolclass=NullPool)
    try:
        version = await _alembic_version(engine)
        assert version == _current_head_revision()
    finally:
        await engine.dispose()


def test_bootstrap_no_longer_branches_on_fresh_vs_existing():
    """AC4, literally: prepare_database must "no longer branch on
    fresh-vs-existing: it just runs `alembic upgrade head`".

    Today it detects "fresh" (no tables at all) and takes a
    create_all-then-stamp path instead of running migrations, keeping a
    second, hand-maintained way to arrive at "head" alongside the migration
    chain itself — precisely the drift risk issue #264 exists to close.
    Once the baseline migration lets `alembic upgrade head` work unmodified
    against an empty database, that branch (and the private helpers behind
    it) has no reason to exist.
    """
    import app.db.bootstrap as bootstrap

    assert not hasattr(bootstrap, "_is_fresh"), (
        "bootstrap still detects fresh-vs-existing databases and branches "
        "on it — prepare_database should unconditionally run "
        "`alembic upgrade head` once a baseline migration exists"
    )
    assert not hasattr(bootstrap, "_create_schema"), (
        "bootstrap still has a create_all fallback path — schema creation "
        "should flow exclusively through the alembic migration chain"
    )


async def test_prepare_database_produces_head_schema_from_legacy_populated_database(
    scratch_db_url: str,
):
    """prepare_database must reach head via the migration path even when the
    target already has a schema and data — not by detecting "non-fresh" and
    merely stamping (today's implementation stamps a *fresh* DB and only runs
    real migrations on a non-fresh one; this asserts the unified behaviour:
    the same function, run against a populated legacy DB, still reaches head
    without wiping or re-creating existing tables/data).
    """
    from app.db.bootstrap import prepare_database

    Base = _import_all_models()

    engine = create_async_engine(scratch_db_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await asyncio.to_thread(_run_alembic_stamp_head, scratch_db_url)

        federation_id = str(uuid.uuid4())
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO federations (id, name, is_pinned, is_active) "
                    "VALUES (:id, :name, false, true)"
                ),
                # Not a FIK affiliate's name: the sync would refuse it (#613).
                {"id": federation_id, "name": "Regional Kendo League"},
            )

        await prepare_database(
            scratch_db_url, app_url(scratch_db_url), max_attempts=1, initial_delay=0.01
        )

        version = await _alembic_version(engine)
        assert version == _current_head_revision()

        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM federations WHERE id = :id"),
                {"id": federation_id},
            )
            row = result.first()
        assert row is not None, "prepare_database lost existing data"
        assert row[0] == "Regional Kendo League"
    finally:
        await engine.dispose()
