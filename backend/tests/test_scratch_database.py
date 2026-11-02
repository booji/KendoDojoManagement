"""Tests for issue #329 — a single module owning "create/drop a throwaway
PostgreSQL database", replacing three near-identical copies of the same
logic (`run_tests.sh`'s two inline python3/asyncpg heredocs, and
`test_migrations.py`'s `_create_scratch_database` / `_drop_scratch_database`
pair), plus a startup sweep that drops databases orphaned by a SIGKILLed
container.

The module under test is `app.db.scratch`, specified (not yet implemented)
as:

    is_safe_identifier(name: str) -> bool
    validate_identifier(name: str) -> None          # raises ValueError
    url_parts(database_url: str) -> tuple[str, str]  # (base_url, db_name)
    asyncpg_dsn(base_url: str, db_name: str) -> str
    async create_database(base_url: str, db_name: str) -> str  # returns full URL
    async drop_database(base_url: str, db_name: str) -> None
    select_sweepable(rows: list[tuple[str, int]], prefix: str = "kendo_test_") -> list[str]
    async sweep_orphaned_databases(base_url: str, prefix: str = "kendo_test_") -> list[str]
    main(argv: list[str] | None = None) -> int      # CLI: create/drop/sweep

`select_sweepable` is the pure heart of the module: given a list of
`(datname, connection_count)` rows (as would come back from a
`pg_stat_activity` join), it returns the subset that are safe to drop — no
live connections, prefix matches. Criteria 4/5/6 from the issue are fully
testable through this one pure function with no live server involved, which
is also the deep-module shape CLAUDE.md asks for: the sweep's real-database
wrapper (`sweep_orphaned_databases`) is a thin shell around it.

No Playwright / `test_e2e_*` stubs accompany this issue, for the same reason
`test_migrations.py` gives for #264: every acceptance criterion here is
about database lifecycle (create/drop/sweep semantics) and shell startup
sequencing in `run_tests.sh`. None of it is observable through a browser —
there is no UI surface for "which throwaway database got swept" — so a
browser stub would fake coverage rather than provide it.
"""

import os
import re

import asyncpg
import pytest

_DATABASE_URL = os.environ["DATABASE_URL"]


def _url_parts(database_url: str) -> tuple[str, str]:
    base, _, db_and_query = database_url.rpartition("/")
    db_name = db_and_query.split("?", 1)[0]
    return base, db_name


_BASE_URL, _ = _url_parts(_DATABASE_URL)


def _plain_dsn(base_url: str, db_name: str) -> str:
    plain = base_url.replace("postgresql+asyncpg://", "postgresql://")
    return f"{plain}/{db_name}"


# ---------------------------------------------------------------------------
# Tier 1 — pure logic, no database. Identifier validation (AC2).
# ---------------------------------------------------------------------------


class TestIsSafeIdentifier:
    def test_accepts_alphanumeric_and_underscore(self):
        from app.db.scratch import is_safe_identifier

        assert is_safe_identifier("kendo_test_abc123") is True
        assert is_safe_identifier("KendoTest_1") is True

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "kendo test",  # space
            "kendo-test",  # hyphen
            "kendo;drop",  # semicolon
            'kendo"test',  # double quote
            "kendo'test",  # single quote
            "kendo_test--comment",
            "kendo_test/*comment*/",
            "kendo_test\ntest",  # newline
            "kendo.test",  # dot
        ],
    )
    def test_rejects_unsafe_names(self, name):
        from app.db.scratch import is_safe_identifier

        assert is_safe_identifier(name) is False


class TestValidateIdentifier:
    def test_accepts_safe_name_without_raising(self):
        from app.db.scratch import validate_identifier

        validate_identifier("kendo_test_abc123")  # must not raise

    @pytest.mark.parametrize(
        "name",
        [
            "kendo test",
            "kendo-test",
            "kendo;drop table members;--",
            'kendo"test',
            "kendo'test",
            "",
        ],
    )
    def test_raises_value_error_for_unsafe_name(self, name):
        from app.db.scratch import validate_identifier

        with pytest.raises(ValueError):
            validate_identifier(name)


# ---------------------------------------------------------------------------
# Tier 1 — pure logic, no database. URL/DSN parsing.
# ---------------------------------------------------------------------------


class TestUrlParts:
    def test_splits_base_url_and_db_name(self):
        from app.db.scratch import url_parts

        base, name = url_parts(
            "postgresql+asyncpg://kendo_test:pw@db:5432/kendo_test_abc123"
        )
        assert base == "postgresql+asyncpg://kendo_test:pw@db:5432"
        assert name == "kendo_test_abc123"

    def test_strips_query_string_from_db_name(self):
        from app.db.scratch import url_parts

        base, name = url_parts(
            "postgresql+asyncpg://kendo_test:pw@db:5432/kendo_test_abc123?ssl=require"
        )
        assert base == "postgresql+asyncpg://kendo_test:pw@db:5432"
        assert name == "kendo_test_abc123"


class TestAsyncpgDsn:
    def test_strips_asyncpg_driver_suffix(self):
        from app.db.scratch import asyncpg_dsn

        dsn = asyncpg_dsn("postgresql+asyncpg://kendo_test:pw@db:5432", "postgres")
        assert dsn == "postgresql://kendo_test:pw@db:5432/postgres"


# ---------------------------------------------------------------------------
# Tier 1 — pure logic, no database. Sweep selection rule (AC4/5/6).
# ---------------------------------------------------------------------------


class TestSelectSweepable:
    def test_selects_orphaned_kendo_test_databases(self):
        from app.db.scratch import select_sweepable

        rows = [
            ("kendo_test_abc123", 0),
            ("kendo_test_def456", 0),
        ]
        assert set(select_sweepable(rows)) == {
            "kendo_test_abc123",
            "kendo_test_def456",
        }

    def test_never_selects_a_database_with_live_connections(self):
        from app.db.scratch import select_sweepable

        rows = [
            ("kendo_test_abc123", 0),
            ("kendo_test_live", 3),
        ]
        result = select_sweepable(rows)
        assert "kendo_test_live" not in result
        assert "kendo_test_abc123" in result

    def test_never_selects_databases_outside_the_kendo_test_prefix(self):
        from app.db.scratch import select_sweepable

        rows = [
            ("postgres", 0),
            ("kendo", 0),
            ("kendo_dev", 0),
            ("kendo_test_abc123", 0),
        ]
        result = select_sweepable(rows)
        assert result == ["kendo_test_abc123"]

    def test_empty_input_selects_nothing(self):
        from app.db.scratch import select_sweepable

        assert select_sweepable([]) == []

    def test_respects_custom_prefix(self):
        from app.db.scratch import select_sweepable

        rows = [("kendo_test_mig_abc", 0), ("kendo_test_abc", 0)]
        result = select_sweepable(rows, prefix="kendo_test_mig_")
        assert result == ["kendo_test_mig_abc"]


# ---------------------------------------------------------------------------
# Tier 2 — real PostgreSQL round-trips (few, per the tdd skill's guidance).
# ---------------------------------------------------------------------------


def _scratch_name(suffix: str) -> str:
    import uuid

    return f"kendo_test_scr_{suffix}_{uuid.uuid4().hex[:8]}"


async def _database_exists(db_name: str) -> bool:
    conn = await asyncpg.connect(_plain_dsn(_BASE_URL, "postgres"))
    try:
        row = await conn.fetchrow(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        return row is not None
    finally:
        await conn.close()


class TestCreateAndDropDatabaseRoundTrip:
    async def test_create_database_actually_creates_it(self):
        from app.db.scratch import create_database, drop_database

        db_name = _scratch_name("create")
        try:
            url = await create_database(_BASE_URL, db_name)
            assert url == f"{_BASE_URL}/{db_name}"
            assert await _database_exists(db_name) is True
        finally:
            await drop_database(_BASE_URL, db_name)

    async def test_drop_database_actually_drops_it(self):
        from app.db.scratch import create_database, drop_database

        db_name = _scratch_name("drop")
        await create_database(_BASE_URL, db_name)
        await drop_database(_BASE_URL, db_name)
        assert await _database_exists(db_name) is False

    async def test_create_database_rejects_unsafe_name(self):
        from app.db.scratch import create_database

        with pytest.raises(ValueError):
            await create_database(_BASE_URL, "kendo_test; DROP DATABASE postgres;--")

    async def test_drop_database_rejects_unsafe_name(self):
        from app.db.scratch import drop_database

        with pytest.raises(ValueError):
            await drop_database(_BASE_URL, "kendo_test'; DROP DATABASE postgres;--")

    async def test_drop_database_terminates_active_backends_first(self):
        """AC3: drop_database must survive a database that still has an open
        connection at the moment drop is requested (ALTER ... ALLOW_CONNECTIONS
        false + pg_terminate_backend before DROP), rather than failing with
        "database is being accessed by other users"."""
        from app.db.scratch import create_database, drop_database

        db_name = _scratch_name("busy")
        await create_database(_BASE_URL, db_name)

        # Open a lingering connection to the scratch database itself.
        lingering = await asyncpg.connect(_plain_dsn(_BASE_URL, db_name))
        try:
            # Must not raise, despite `lingering` still being connected.
            await drop_database(_BASE_URL, db_name)
        finally:
            with pytest.raises((asyncpg.PostgresError, OSError, Exception)):
                # The connection should have been forcibly terminated by the
                # drop; if it wasn't, close() below is harmless either way,
                # so this assertion only documents intent and never masks a
                # real failure of the primary assertion above.
                await lingering.execute("SELECT 1")
            await lingering.close()

        assert await _database_exists(db_name) is False


class TestSweepOrphanedDatabases:
    async def test_sweep_drops_orphaned_database_with_no_connections(self):
        from app.db.scratch import create_database, sweep_orphaned_databases

        db_name = _scratch_name("orphan")
        await create_database(_BASE_URL, db_name)

        dropped = await sweep_orphaned_databases(_BASE_URL)

        assert db_name in dropped
        assert await _database_exists(db_name) is False

    async def test_sweep_never_drops_a_database_with_live_connections(self):
        """AC5, against a live server: a sweep run while another "run" is
        still connected must leave that database alone — this is what makes
        the sweep safe against concurrent test-suite runs."""
        from app.db.scratch import (
            create_database,
            drop_database,
            sweep_orphaned_databases,
        )

        db_name = _scratch_name("live")
        await create_database(_BASE_URL, db_name)
        holder = await asyncpg.connect(_plain_dsn(_BASE_URL, db_name))
        try:
            dropped = await sweep_orphaned_databases(_BASE_URL)
            assert db_name not in dropped
            assert await _database_exists(db_name) is True
        finally:
            await holder.close()
            await drop_database(_BASE_URL, db_name)

    async def test_sweep_never_touches_databases_outside_the_prefix(self):
        """AC6, against a live server: sweeping must never even consider
        (let alone drop) `postgres`, the running test database, or anything
        else not matching the kendo_test_ prefix."""
        from app.db.scratch import sweep_orphaned_databases

        dropped = await sweep_orphaned_databases(_BASE_URL)

        assert "postgres" not in dropped
        _, running_db_name = _url_parts(_DATABASE_URL)
        assert running_db_name not in dropped


# ---------------------------------------------------------------------------
# Tier 1 — static text assertions against run_tests.sh (AC7/8/9).
# ---------------------------------------------------------------------------


def _run_tests_sh_text() -> str:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(backend_dir, "run_tests.sh")
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestRunTestsShUsesScratchModule:
    def test_invokes_scratch_module_as_cli(self):
        script = _run_tests_sh_text()
        assert (
            "python -m app.db.scratch" in script
            or "python3 -m app.db.scratch" in script
        ), (
            "run_tests.sh should invoke the new app.db.scratch CLI instead of "
            "its inline python3/asyncpg heredocs"
        )

    def test_no_longer_contains_inline_asyncpg_heredocs(self):
        script = _run_tests_sh_text()
        assert "import asyncpg" not in script, (
            "run_tests.sh still has an inline python3/asyncpg heredoc — this "
            "logic should live exclusively in app.db.scratch"
        )

    def test_sweep_runs_before_the_per_run_database_is_created(self):
        script = _run_tests_sh_text()
        sweep_pos = script.find("sweep")
        create_pos = script.find("python -m app.db.scratch create")
        if create_pos == -1:
            create_pos = script.find("python3 -m app.db.scratch create")
        assert sweep_pos != -1, "run_tests.sh has no sweep invocation at all"
        assert create_pos != -1, "run_tests.sh has no scratch-module create invocation"
        assert sweep_pos < create_pos, (
            "the sweep must run before run_tests.sh creates its own per-run "
            "database (issue #329 AC8)"
        )

    def test_cleanup_still_guarded_by_test_db_created(self):
        script = _run_tests_sh_text()
        assert "TEST_DB_CREATED" in script, (
            "run_tests.sh must still guard cleanup()'s drop behind "
            "TEST_DB_CREATED=1 — a run must never drop a database it did "
            "not create (issue #329 AC9)"
        )
        # The guard must appear inside the body of cleanup(), not merely
        # anywhere in the file.
        cleanup_match = re.search(r"cleanup\(\)\s*\{(.*?)\n\}", script, re.DOTALL)
        assert cleanup_match is not None, "could not locate cleanup() function body"
        assert "TEST_DB_CREATED" in cleanup_match.group(1), (
            "TEST_DB_CREATED guard must live inside cleanup()'s own body"
        )

    def test_sweep_invocation_is_commented_as_a_deliberate_exception(self):
        """AC9: the sweep is a deliberate, explicitly-commented exception to
        "a run never drops a database it did not create" — it must say so."""
        script = _run_tests_sh_text()
        sweep_pos = script.find("sweep")
        assert sweep_pos != -1
        # Look at the ~500 chars preceding the sweep invocation for a comment
        # explaining the exception.
        window = script[max(0, sweep_pos - 600) : sweep_pos]
        assert "#" in window, (
            "the sweep invocation in run_tests.sh should be preceded by a "
            "comment explaining that it is a deliberate exception to the "
            "TEST_DB_CREATED-only-drops-what-it-made rule"
        )


class TestSweepPrefixFloor:
    """The sweep DROPs whatever it selects, so `prefix` is its entire blast
    radius. `--prefix ""` would make `startswith` true for every database on
    the server, so the CLI refuses to widen it below a floor."""

    def test_cli_refuses_an_empty_prefix(self, capsys):
        from app.db.scratch import main

        assert main(["sweep", "--prefix", ""]) == 1
        assert "refusing to sweep" in capsys.readouterr().out

    def test_cli_refuses_an_unrelated_prefix(self, capsys):
        from app.db.scratch import main

        assert main(["sweep", "--prefix", "kendo_"]) == 1
        assert "refusing to sweep" in capsys.readouterr().out

    def test_default_prefix_is_within_the_floor(self):
        from app.db.scratch import _SWEEP_PREFIX_FLOOR, select_sweepable

        assert select_sweepable([("kendo_dev", 0), ("postgres", 0)]) == []
        assert _SWEEP_PREFIX_FLOOR == "kendo_test"


class TestRunTestsShHoldsASentinelConnection:
    """The sweep spares any database with a live backend. That rule only
    protects a concurrently starting run if such a backend actually exists —
    and the app provides none between CREATE DATABASE and the first
    database-touching test (/health does no DB I/O, the engine is lazy, and
    bootstrap disposes its own engine). run_tests.sh must therefore hold a
    sentinel connection open for the life of the run."""

    def test_holds_a_connection_for_the_life_of_the_run(self):
        script = _run_tests_sh_text()
        assert "python -m app.db.scratch hold" in script, (
            "run_tests.sh must hold a sentinel connection to its own database, "
            "or a concurrent run's sweep can drop it mid-startup"
        )

    def test_sentinel_starts_after_create_and_before_the_servers(self):
        script = _run_tests_sh_text()
        create_pos = script.find("app.db.scratch create")
        hold_pos = script.find("app.db.scratch hold")
        uvicorn_pos = script.find("uvicorn app.main:app")
        assert -1 not in (create_pos, hold_pos, uvicorn_pos)
        assert create_pos < hold_pos < uvicorn_pos, (
            "the sentinel must attach as soon as the database exists — before "
            "the readiness gates, which are the longest connectionless window"
        )

    def test_sentinel_is_released_in_cleanup(self):
        script = _run_tests_sh_text()
        cleanup_match = re.search(r"cleanup\(\)\s*\{(.*?)\n\}", script, re.DOTALL)
        assert cleanup_match is not None
        assert "DB_HOLD_PID" in cleanup_match.group(1), (
            "cleanup() must release the sentinel connection"
        )


class TestSweepGraceWindow:
    """A single observation is not enough. A run's database is genuinely
    connectionless in the sliver between CREATE DATABASE returning and its
    sentinel attaching, so the sweep requires a database to look orphaned
    twice, a grace period apart, before dropping it."""

    async def test_spares_a_database_connected_to_during_the_grace_window(self):
        import asyncio

        from app.db.scratch import (
            asyncpg_dsn,
            create_database,
            drop_database,
            sweep_orphaned_databases,
        )

        db_name = _scratch_name("grace")
        await create_database(_BASE_URL, db_name)
        late_conn = None
        try:
            sweep = asyncio.create_task(
                sweep_orphaned_databases(_BASE_URL, grace_seconds=3.0)
            )
            # Let the first observation see it as an orphan, then attach the
            # way a starting run's sentinel would.
            await asyncio.sleep(0.75)
            late_conn = await asyncpg.connect(asyncpg_dsn(_BASE_URL, db_name))
            dropped = await sweep

            assert db_name not in dropped, (
                "a database connected to during the grace window must be "
                "spared — this is the concurrent-startup case that would "
                "otherwise reintroduce #316"
            )
            check = await asyncpg.connect(asyncpg_dsn(_BASE_URL, "postgres"))
            try:
                assert await check.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = $1", db_name
                ), "the spared database should still exist"
            finally:
                await check.close()
        finally:
            if late_conn is not None:
                await late_conn.close()
            await drop_database(_BASE_URL, db_name)


class TestCleanupIsCwdIndependent:
    """cleanup() runs with whatever the current directory is AT EXIT, not at
    definition. run_tests.sh cds to /frontend to start Vite and does not cd
    back until just before pytest, so an exit in between — an ordinary
    readiness-gate failure, not just a signal — ran the drop from /frontend
    where the `app` package is not importable, leaking the database with only
    a warning. Observed live during QA of #329."""

    def test_drop_invocation_sets_its_own_working_directory(self):
        script = _run_tests_sh_text()
        cleanup_match = re.search(r"cleanup\(\)\s*\{(.*?)\n\}", script, re.DOTALL)
        assert cleanup_match is not None, "could not locate cleanup() function body"
        body = cleanup_match.group(1)
        assert "app.db.scratch drop" in body
        assert "cd /app" in body, (
            "cleanup()'s drop must set its own working directory: it can fire "
            "while the script is cd'd to /frontend, where `python -m "
            "app.db.scratch` raises ModuleNotFoundError and the database leaks"
        )

    def test_the_cd_does_not_escape_cleanup(self):
        """The cd belongs in a subshell so it cannot leak into whatever else
        runs on the exit path."""
        script = _run_tests_sh_text()
        cleanup_match = re.search(r"cleanup\(\)\s*\{(.*?)\n\}", script, re.DOTALL)
        assert cleanup_match is not None
        assert "(cd /app" in cleanup_match.group(1), (
            "wrap the cd in a subshell so it does not change the caller's cwd"
        )
