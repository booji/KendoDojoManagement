"""Tests for schema ownership in backend/tests/conftest.py (Issue #316,
root-cause fix).

Two concurrent test runs against the shared `kendo_test` database step on
each other: one run's session teardown (`_setup_schema`'s `drop_all` +
`DROP TABLE IF EXISTS alembic_version`) destroys the schema out from under
another run's still-live uvicorn server, producing a wall of unrelated-
looking `UndefinedTableError` failures. The chosen fix (see run_tests.sh
changes covered in test_run_tests_script_db_isolation.py) gives every suite
run its own throwaway database and makes the server's own `alembic upgrade
head` (run via `prepare_database()` during uvicorn's lifespan) the *sole*
schema owner. conftest.py's `_setup_schema` must stop building and tearing
down the schema itself — with one owner, there is nothing left to race.

If pytest is ever started outside run_tests.sh (so nothing ran migrations
first), the schema-less database must fail loudly with ONE clear diagnostic
naming run_tests.sh, not a wall of per-test UndefinedTableError.

No live database is required for any of these — they inspect conftest.py's
source text, or exercise its module-level import guards in a subprocess
without ever connecting to PostgreSQL (those guards raise before any DB
connection is opened).

No Playwright / test_e2e_* stubs: schema ownership and startup diagnostics
are test-harness/DB-process concerns, not observable through a browser.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)
CONFTEST = ROOT / "backend" / "tests" / "conftest.py"
TESTS_DIR = ROOT / "backend" / "tests"


def _conftest_text() -> str:
    return CONFTEST.read_text()


def _setup_schema_region() -> str:
    """The body of the `_setup_schema` fixture: from `def _setup_schema(`
    up to (but not including) the next non-indented line, which marks the
    start of whatever follows it at module level.
    """
    text = _conftest_text()
    start = re.search(r"def _setup_schema\(", text)
    assert start, "could not find '_setup_schema' fixture in conftest.py"
    after = text[start.end() :]
    next_top_level = re.search(r"\n(?=\S)", after)
    return after[: next_top_level.start()] if next_top_level else after


# ---------------------------------------------------------------------------
# Criterion 4 — exactly one schema owner: conftest must stop building/
# tearing down the schema itself
# ---------------------------------------------------------------------------


def test_conftest_no_longer_calls_create_all():
    """Criterion 4: with the server's own `alembic upgrade head` as the sole
    schema owner, conftest.py must not also build the schema via
    `Base.metadata.create_all` — two builders racing (or one building while
    the other assumes it already exists) is exactly the class of bug #316
    is about.
    """
    text = _conftest_text()
    assert "create_all" not in text, (
        "expected conftest.py to no longer call Base.metadata.create_all — "
        "the server's own 'alembic upgrade head' (via prepare_database()) "
        "must be the sole schema owner, not a second builder in the test "
        "harness"
    )


def test_conftest_no_longer_calls_drop_all():
    """Criterion 4: nor may conftest.py tear the schema down via
    `Base.metadata.drop_all` — that's the exact call whose teardown, in the
    reproduced #316 failure, destroyed the schema out from under a second,
    still-live concurrent run. With a dedicated per-run database (dropped
    wholesale by run_tests.sh instead), there is nothing left for conftest
    to selectively tear down.
    """
    text = _conftest_text()
    assert "drop_all" not in text, (
        "expected conftest.py to no longer call Base.metadata.drop_all — "
        "the throwaway per-run database is dropped wholesale by "
        "run_tests.sh instead, so the test harness has no schema-teardown "
        "responsibility left"
    )


def test_conftest_no_longer_drops_alembic_version_table():
    """Criterion 4: the explicit `DROP TABLE IF EXISTS alembic_version`
    (needed today only to compensate for drop_all leaving it behind) must go
    with it — once conftest isn't tearing down the schema at all, there's
    nothing to compensate for.
    """
    text = _conftest_text()
    assert "alembic_version" not in text or "DROP TABLE" not in text.upper(), (
        "expected conftest.py to no longer issue 'DROP TABLE ... "
        "alembic_version' — that statement only exists today to clean up "
        "after Base.metadata.drop_all, which criterion 4 also removes"
    )


# ---------------------------------------------------------------------------
# Criterion 5 — a schema-less database fails fast with ONE clear diagnostic
# naming run_tests.sh, instead of a wall of UndefinedTableError
# ---------------------------------------------------------------------------

# A bare keyword search for "alembic_version"/"inspect("/etc. is not enough
# to tell a real presence *check* apart from the unmodified fixture's own
# `DROP TABLE IF EXISTS alembic_version` statement and its neighbouring
# comment (both of which already contain "alembic_version" and even
# "run_tests.sh" today, so a naive substring test would pass vacuously
# against the current, unfixed code). Filter out any matching line that is
# itself part of the create/drop machinery criterion 4 removes.
_SCHEMA_CHECK_KEYWORDS_RE = re.compile(
    r"alembic_version|\.has_table\(|information_schema|inspect\(", re.IGNORECASE
)
_CREATE_OR_DROP_RE = re.compile(r"DROP\s+TABLE|create_all|drop_all", re.IGNORECASE)


def _find_real_presence_check(region: str) -> re.Match | None:
    """A line matching the schema-check keywords that is NOT itself a
    create/drop statement (or the unmodified fixture's leftover comment
    about one).
    """
    for line_match in re.finditer(r"^.*$", region, re.MULTILINE):
        line = line_match.group(0)
        if _SCHEMA_CHECK_KEYWORDS_RE.search(line) and not _CREATE_OR_DROP_RE.search(
            line
        ):
            return line_match
    return None


def _find_diagnostic_raise(region: str) -> re.Match | None:
    """A `raise ...(` or `pytest.fail(` whose message mentions run_tests.sh,
    within the same statement (bounded to avoid matching across unrelated
    code). The unmodified fixture has no raise/fail at all inside
    `_setup_schema` — its only mention of "run_tests.sh" is an unrelated
    explanatory comment on the (soon to be deleted) drop_all cleanup code.
    """
    return re.search(
        r"(raise\s+\w+\(|pytest\.fail\()[\s\S]{0,400}?run_tests\.sh", region
    )


def test_setup_schema_verifies_schema_presence_before_yielding():
    """Criterion 5: once conftest stops building the schema itself
    (criterion 4), it must instead *check* that a schema already exists —
    otherwise a stray `pytest` run outside run_tests.sh silently proceeds
    into a schema-less database and every DB-touching test fails
    individually with its own UndefinedTableError, which is the exact
    confusing-failure class #316 is about (just moved from "two runs
    collided" to "no migration ever ran").

    Structural: look for a presence check (querying `alembic_version`,
    using SQLAlchemy's inspector/`has_table`, or querying
    `information_schema`) inside `_setup_schema`, excluding the unmodified
    fixture's own create/drop statements and comments about them (which
    already contain some of these keywords without performing any check).
    The current fixture does no real check — it unconditionally creates the
    schema itself — so this fails against the unmodified conftest.py.
    """
    region = _setup_schema_region()
    assert _find_real_presence_check(region), (
        "expected '_setup_schema' to check for an existing migrated schema "
        "(e.g. via alembic_version, SQLAlchemy's inspector/has_table, or "
        "information_schema) before yielding to the test session — found "
        "no such check (only, at most, the unmodified fixture's own "
        "create/drop statements, which criterion 4 removes and which don't "
        "count as a presence check)"
    )


def test_missing_schema_diagnostic_names_run_tests_sh():
    """Criterion 5: when the check above finds no schema, the failure
    message must point the reader at run_tests.sh — the one place that's
    supposed to have created and migrated this database already — rather
    than leaving them to debug a wall of unrelated per-test
    UndefinedTableError.

    We require the "run_tests.sh" mention to appear inside an actual
    `raise ...(` or `pytest.fail(` call, not merely anywhere in the fixture
    — the unmodified fixture already happens to mention "run_tests.sh" in
    an explanatory *comment* on unrelated cleanup code, which a bare
    substring search would match vacuously.
    """
    region = _setup_schema_region()
    assert _find_diagnostic_raise(region), (
        "expected the schema-presence check in '_setup_schema' to raise "
        "(or pytest.fail) with a message naming 'run_tests.sh' when no "
        "schema is found, so a stray bare-pytest run fails with one clear "
        "message instead of a wall of UndefinedTableError from every "
        "DB-touching test — found no such raise/fail (only, at most, an "
        "unrelated comment mentioning run_tests.sh on the create/drop code "
        "criterion 4 removes)"
    )


def test_schema_presence_check_happens_before_yield():
    """Criterion 5: the check (and its diagnostic) must gate the whole
    session — it has to run before `_setup_schema`'s `yield`, otherwise
    tests would already be running (and failing individually) by the time
    the missing schema is noticed.
    """
    region = _setup_schema_region()
    check_match = _find_real_presence_check(region)
    yield_match = re.search(r"^\s*yield\b", region, re.MULTILINE)
    assert check_match, "no schema-presence check found (see previous test)"
    assert yield_match, "'_setup_schema' has no 'yield' — cannot be a fixture"
    assert check_match.start() < yield_match.start(), (
        "expected the schema-presence check to run before '_setup_schema' "
        "yields, so a missing schema is reported once, up front, before "
        "any test in the session gets a chance to run and fail on its own"
    )


# ---------------------------------------------------------------------------
# Criterion 6 — existing conftest safety guards still hold
# ---------------------------------------------------------------------------


def _run_guard_in_subprocess(database_url: str) -> subprocess.CompletedProcess:
    """Import conftest.py fresh in a subprocess with the given DATABASE_URL.

    The guards under test live at module level, at the very top of
    conftest.py, before any heavier (app-internal) imports — they raise
    (or don't) purely from string inspection of DATABASE_URL, with no
    database connection involved. Running in a subprocess (rather than
    importlib.reload in-process) is necessary because these are genuine
    module-level side effects on first import, and this suite's own
    conftest.py is already loaded by the time any test body runs.
    """
    code = "import sys; " f"sys.path.insert(0, {str(TESTS_DIR)!r}); " "import conftest"
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT / "backend"),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_non_postgres_database_url_still_refused():
    """Criterion 6 (regression guard): a non-PostgreSQL DATABASE_URL must
    still be refused with a RuntimeError, unchanged by the schema-ownership
    refactor. This already passes against the unmodified conftest.py — it
    protects against the refactor accidentally weakening or removing the
    guard while restructuring the surrounding module-level code.
    """
    # A MySQL URL: the repo-wide guard from #269 forbids naming the retired
    # file-based engine anywhere outside historical migrations, so any URL
    # standing in for "not PostgreSQL" has to use a different one.
    result = _run_guard_in_subprocess("mysql+aiomysql://user:pw@localhost/kendo_test")
    assert result.returncode != 0, (
        "expected conftest.py import to fail (non-zero exit) for a "
        "non-PostgreSQL DATABASE_URL, but it succeeded"
    )
    assert "RuntimeError" in result.stderr, (
        f"expected a RuntimeError for a non-PostgreSQL DATABASE_URL; "
        f"stderr was:\n{result.stderr}"
    )
    assert (
        "postgresql" in result.stderr.lower()
    ), f"expected the failure to mention PostgreSQL; stderr was:\n{result.stderr}"


def test_non_test_named_database_still_refused():
    """Criterion 6 (regression guard): a DATABASE_URL naming a database
    without "test" in it must still be refused with a RuntimeError. This
    guard exists specifically so a misdirected DATABASE_URL can't have its
    schema wiped — that risk doesn't go away when conftest stops calling
    drop_all itself, because run_tests.sh's new per-run database is dropped
    wholesale on exit, which is just as destructive if pointed at the wrong
    database.
    """
    result = _run_guard_in_subprocess(
        "postgresql+asyncpg://kendo:kendo@db:5432/kendo_production"
    )
    assert result.returncode != 0, (
        "expected conftest.py import to fail (non-zero exit) for a database "
        "name without 'test' in it, but it succeeded"
    )
    assert "RuntimeError" in result.stderr, (
        f"expected a RuntimeError for a non-test database name; "
        f"stderr was:\n{result.stderr}"
    )


def test_non_test_named_database_guard_message_no_longer_blames_drop_all():
    """Criterion 6 + criterion 4, combined: the guard's current message
    justifies itself by name-checking "the suite calls Base.metadata.drop_all
    on teardown and would destroy all of its data" — criterion 4 removes
    that call, which would make the message false. The refactor must update
    the message to justify the guard on grounds that remain true afterward
    (e.g. run_tests.sh dropping the per-run database wholesale on exit is
    just as destructive if misdirected) rather than leaving a stale claim
    about a code path that no longer exists.

    This fails against the unmodified conftest.py, whose message still
    names drop_all.
    """
    result = _run_guard_in_subprocess(
        "postgresql+asyncpg://kendo:kendo@db:5432/kendo_production"
    )
    assert "RuntimeError" in result.stderr, (
        f"expected a RuntimeError for a non-test database name; "
        f"stderr was:\n{result.stderr}"
    )
    assert "drop_all" not in result.stderr, (
        "expected the guard's message to no longer justify itself by "
        "naming Base.metadata.drop_all, since criterion 4 removes that "
        f"call — the message would be describing dead code. stderr was:\n"
        f"{result.stderr}"
    )
