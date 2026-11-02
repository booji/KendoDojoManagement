"""File-based tests for per-run database isolation in backend/run_tests.sh
(Issue #316, root-cause fix).

The readiness gate added for #316 (see test_run_tests_script.py) turned out
not to be the real bug: it was verified directly that uvicorn never accepts a
connection until app.main's lifespan (which runs migrations) has completed, so
pytest can never start against a half-migrated server.

The REAL cause, reproduced deliberately: docker-compose.test.yml pins
`name: kendodojo-test`, so every worktree / parallel agent run shares ONE
`kendodojo-test_db_1` container and ONE `kendo_test` database. Two concurrent
suites stepped on each other: one suite's session teardown dropped the schema
while another suite's live uvicorn was still serving requests against it,
producing a wall of `UndefinedTableError`.

The fix: run_tests.sh must give every invocation its own throwaway database —
derive a unique per-run name (still containing "test", since conftest.py
refuses to run against a database whose name doesn't), create it, export
DATABASE_URL so both the uvicorn process it starts and the pytest process it
execs point at that same database, and drop it on exit (success or failure)
via the existing EXIT trap.

These tests inspect run_tests.sh as text on disk — no live Docker, no running
servers, no database required. Following the pattern established in
test_run_tests_script.py, they assert on STRUCTURAL properties (a per-run name
computed, a creation command issued, DATABASE_URL exported before the server
processes start, a drop command reachable from the EXIT trap) rather than
pinning exact command syntax, so the implementing agent retains freedom of
phrasing (createdb vs. psql vs. a Python one-liner, uuid vs. $$ vs. RANDOM,
etc.).
"""

import os
import re
from pathlib import Path

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)
RUN_TESTS_SCRIPT = ROOT / "backend" / "run_tests.sh"


def _script_text() -> str:
    return RUN_TESTS_SCRIPT.read_text()


def _pre_uvicorn_region() -> str:
    """Text from the start of the script up to the `uvicorn app.main:app`
    invocation. A per-run database must be named, created, and exported here
    (or earlier) — uvicorn's own lifespan runs migrations against whatever
    DATABASE_URL it inherits, so the export must happen before it starts.
    """
    text = _script_text()
    uvicorn_match = re.search(r"^\s*uvicorn\s+app\.main:app", text, re.MULTILINE)
    assert uvicorn_match, "could not find the 'uvicorn app.main:app' invocation"
    return text[: uvicorn_match.start()]


def _cleanup_function_region() -> str:
    """The body of the `cleanup()` function that the EXIT trap calls.

    Matches the existing single-line-brace style (`cleanup() { ...; }`) as
    well as a multi-line `cleanup() {\n ... \n}` form, so the implementer
    isn't forced to keep the one-liner shape just to satisfy this test.
    """
    text = _script_text()
    # Single-line form: cleanup() { ...anything up to the matching close-brace on
    # the same or a later line... }
    match = re.search(r"cleanup\(\)\s*\{(.*?)\n\}\n", text, re.DOTALL)
    if match:
        return match.group(1)
    match = re.search(r"cleanup\(\)\s*\{(.*?)\}", text, re.DOTALL)
    assert match, "could not find a 'cleanup()' function definition in run_tests.sh"
    return match.group(1)


def test_trap_still_calls_a_cleanup_function_on_exit():
    """Regression guard: the EXIT trap wiring itself must survive — the drop
    of the per-run database has to be reachable from it (criterion 3), so
    there needs to still be a `trap <fn> EXIT` calling a function whose body
    we can inspect.
    """
    text = _script_text()
    assert re.search(r"^\s*trap\s+\w+\s+EXIT\s*$", text, re.MULTILINE), (
        "expected 'trap <function> EXIT' to still be present so cleanup "
        "(including dropping the per-run database) runs on both the success "
        "and failure paths"
    )


# ---------------------------------------------------------------------------
# Criterion 1 — a unique per-run database name, still containing "test"
# ---------------------------------------------------------------------------

_UNIQUENESS_TOKEN_RE = re.compile(
    r"\$\$|\$RANDOM|\bRANDOM\b|uuidgen|mktemp|date\s+\+%s|python3?\s+-c|/dev/urandom"
)


def test_script_computes_a_unique_per_run_database_name():
    """Criterion 1: run_tests.sh must derive a database name that is unique
    per invocation (so concurrent runs never collide) and still contains
    "test" (conftest.py's guard refuses any DATABASE_URL naming a database
    without "test" in it — see conftest.py's module-level checks).

    We look for a variable assignment whose right-hand side both mentions
    "test" and includes some source of per-invocation uniqueness (PID via
    $$, $RANDOM, uuidgen, mktemp, a timestamp, or a one-off python/uuid
    call). The current script does nothing of the sort — it never computes a
    database name at all, it just inherits DATABASE_URL unchanged from
    .env.test — so this fails against the unmodified script.
    """
    region = _pre_uvicorn_region()
    assignment_lines = re.findall(
        r"^\s*[A-Za-z_][A-Za-z0-9_]*=.*$", region, re.MULTILINE
    )
    candidates = [
        line
        for line in assignment_lines
        if "test" in line.lower() and _UNIQUENESS_TOKEN_RE.search(line)
    ]
    assert candidates, (
        "expected an assignment before the uvicorn/pytest processes start "
        "that computes a per-run database name containing 'test' plus some "
        "uniqueness token ($$, $RANDOM, uuidgen, mktemp, a timestamp, or a "
        "one-off python/uuid call) — found none. The unmodified script never "
        "computes a database name at all; it reuses the shared DATABASE_URL "
        "from .env.test unchanged, which is the root cause of #316"
    )


# ---------------------------------------------------------------------------
# Criterion 2 — the per-run database is created, and DATABASE_URL exported
# for both uvicorn and pytest
# ---------------------------------------------------------------------------


def test_script_creates_the_per_run_database_before_starting_uvicorn():
    """Criterion 2: the per-run database must actually be created (not just
    named) before uvicorn starts, since uvicorn's lifespan runs `alembic
    upgrade head` against whatever DATABASE_URL it inherits and needs a real
    database to connect to.

    Structural: look for a database-creation command (createdb, `CREATE
    DATABASE`, or an equivalent psql/python invocation) anywhere before the
    uvicorn invocation. The unmodified script issues no such command.
    """
    region = _pre_uvicorn_region()
    assert re.search(r"createdb\b|CREATE\s+DATABASE", region, re.IGNORECASE), (
        "expected a database-creation command (e.g. createdb, or "
        "'CREATE DATABASE' via psql/python) before uvicorn starts, so the "
        "per-run database actually exists when uvicorn's lifespan tries to "
        "migrate it — found none"
    )


def test_script_exports_database_url_before_starting_uvicorn():
    """Criterion 2: DATABASE_URL must be (re-)exported to point at the
    per-run database before uvicorn starts, and as an `export` (not just a
    local shell variable) so the later `exec pytest` — which replaces this
    same shell process — inherits the same value.

    The unmodified script never touches DATABASE_URL at all; it comes
    entirely from .env.test via docker-compose's `env_file`, unchanged.
    """
    region = _pre_uvicorn_region()
    assert re.search(r"^\s*export\s+DATABASE_URL=", region, re.MULTILINE), (
        "expected 'export DATABASE_URL=...' before the uvicorn invocation, "
        "pointing at the newly-created per-run database, so both uvicorn "
        "and the later 'exec pytest' (same process, via exec) see the same "
        "DATABASE_URL — found no such export"
    )


def test_database_url_export_references_the_computed_db_name_not_env_test():
    """Criterion 1+2 combined: the exported DATABASE_URL must be built from
    the per-run name computed above, not simply re-exported unchanged from
    whatever .env.test already set. We check this by requiring the export
    line (or the immediately preceding derivation) to reference a shell
    variable — i.e. the export's value is not a bare literal matching the
    static kendo_test database name from .env.test.
    """
    region = _pre_uvicorn_region()
    export_match = re.search(r"^\s*export\s+DATABASE_URL=(.*)$", region, re.MULTILINE)
    assert export_match, "expected an 'export DATABASE_URL=' line (see previous test)"
    rhs = export_match.group(1)
    assert re.search(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", rhs), (
        "expected the exported DATABASE_URL to be built from a shell "
        f"variable (the computed per-run database name), not a static "
        f"literal — got: {rhs!r}"
    )


# ---------------------------------------------------------------------------
# Criterion 3 — the per-run database is dropped from the EXIT trap
# ---------------------------------------------------------------------------


def test_cleanup_function_drops_the_per_run_database():
    """Criterion 3: the per-run database must be dropped on exit, on the
    failure path as well as the success path. Since `trap cleanup EXIT`
    fires on any exit (normal, `exit 1` from the readiness gates, or a
    failing pytest under `set -e`), the drop belongs inside the existing
    `cleanup()` function alongside the current `kill "$BACKEND_PID"
    "$FRONTEND_PID"` — not gated behind a successful pytest run.

    Structural: look for a database-drop command (dropdb, `DROP DATABASE`,
    or an equivalent psql/python invocation) inside cleanup()'s body. The
    unmodified cleanup() only kills the two server processes.

    The `app.db.scratch drop` alternative is the "equivalent python
    invocation" this test always allowed for: #329 moved the DDL itself out
    of this script into that module, so the literal `DROP DATABASE` no
    longer appears here. What matters is that cleanup() still drops, not
    which layer spells out the SQL.
    """
    region = _cleanup_function_region()
    assert re.search(
        r"dropdb\b|DROP\s+DATABASE|app\.db\.scratch\s+drop", region, re.IGNORECASE
    ), (
        "expected a database-drop command (e.g. dropdb, 'DROP DATABASE' via "
        "psql/python, or `python -m app.db.scratch drop`) inside cleanup(), so "
        "the per-run database is removed on both the success and failure exit "
        "paths — found none. The unmodified cleanup() only kills BACKEND_PID "
        "and FRONTEND_PID"
    )


def test_cleanup_still_kills_backend_and_frontend_processes():
    """Regression guard: the new database-drop logic must not replace the
    existing process cleanup — both BACKEND_PID and FRONTEND_PID must still
    be killed, or the server processes leak on every run.
    """
    region = _cleanup_function_region()
    assert "BACKEND_PID" in region and "FRONTEND_PID" in region, (
        "expected cleanup() to still kill both BACKEND_PID and FRONTEND_PID "
        "alongside the new per-run database drop"
    )


# ---------------------------------------------------------------------------
# Criterion 3, behavioural counterpart — the EXIT trap must actually be able
# to run
# ---------------------------------------------------------------------------


def test_pytest_is_not_exec_d_so_the_exit_trap_can_still_run():
    """`exec pytest` replaces the shell process image, which discards its
    traps — so `trap cleanup EXIT` never fires and the per-run database is
    never dropped, however correct cleanup()'s body is.

    This is not theoretical: with cleanup() fully implemented and `exec
    pytest` still in place, three consecutive runs that each exited 0 left
    kendo_test_8333bd5d55574b81, kendo_test_45fa1a262ed6453b and
    kendo_test_a627ac51b75943ec behind on the server. Every other test in
    this file inspects cleanup()'s *text*, which cannot catch that.

    The script must therefore run pytest as a child, then exit with its
    status so the trap runs in between and the exit code still propagates.
    """
    text = _script_text()
    assert not re.search(r"^\s*exec\s+pytest", text, re.MULTILINE), (
        "run_tests.sh must not 'exec pytest': exec replaces the shell "
        "process and discards its EXIT trap, so cleanup() never runs and "
        "the per-run database leaks on every invocation. Run pytest as a "
        "child process and exit with its status instead."
    )
    assert re.search(r"^\s*pytest\s", text, re.MULTILINE), (
        "expected a plain 'pytest ...' invocation in run_tests.sh"
    )
    assert re.search(r"^\s*exit\s+\"?\$", text, re.MULTILINE), (
        "expected run_tests.sh to exit with pytest's captured status "
        "(e.g. 'exit \"$status\"'), so the EXIT trap runs but a failing "
        "suite still fails the container"
    )
