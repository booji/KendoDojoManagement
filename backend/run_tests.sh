#!/usr/bin/env bash
# Starts backend + frontend servers, then runs the full test suite.
# Used as the entrypoint for docker-compose.test.yml.
set -euo pipefail

# BACKEND_ONLY=1 runs the fast half of the suite: no frontend install, no Vite,
# no e2e collection (#336). Private-repo Actions minutes are metered and the
# full suite is ~15 minutes, almost all of it the 50-odd Playwright files, so
# CI fires this mode on every push and the full suite only on release tags.
# The backend server still starts — see the uvicorn note below.
BACKEND_ONLY="${BACKEND_ONLY:-0}"

# Install frontend dependencies
if [[ "$BACKEND_ONLY" != "1" ]]; then
    cd /frontend
    npm ci --prefer-offline
fi

# Give this invocation its own throwaway database (#316). Sharing the one
# `kendo_test` database across every worktree / parallel agent run meant a
# fast run's teardown could drop the schema out from under a still-live
# concurrent run's uvicorn server, producing a wall of unrelated-looking
# UndefinedTableError. TEST_DB_NAME is built only from a kernel UUID (or
# numeric $$/$RANDOM as a fallback), so it can never carry shell/SQL
# metacharacters — but the name is still validated defensively (identifier
# characters only) before being interpolated into any SQL below, since that
# interpolation is a security boundary, not just formatting.
cd /app
# $$ is always 1 in a container, so the PID contributes nothing to uniqueness
# here: the entropy has to come from elsewhere. $RANDOM alone spans only 32768
# values, and a collision between two *concurrent* runs would be silent and
# lethal — the loser fails to CREATE, its EXIT trap fires, and it drops the
# winner's database, which is precisely the #316 failure this whole change
# exists to remove. Prefer the kernel's UUID source, falling back to $RANDOM
# only if it is unavailable.
if [[ -r /proc/sys/kernel/random/uuid ]]; then
    TEST_DB_SUFFIX="$(tr -d - < /proc/sys/kernel/random/uuid | cut -c1-16)"
else
    TEST_DB_SUFFIX="$$_${RANDOM}${RANDOM}"
fi
TEST_DB_NAME="kendo_test_${TEST_DB_SUFFIX}"
if [[ ! "$TEST_DB_NAME" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "ERROR: computed test database name '$TEST_DB_NAME' contains unsafe characters — aborting" >&2
    exit 1
fi

# DATABASE_URL from .env.test names the shared 'kendo_test' database; swap in
# the per-run name and create it before anything connects. app.db.scratch
# (backed by asyncpg, already a dependency of the app) does the actual DDL
# rather than shelling out to a psql/createdb client this image doesn't
# install.
TEST_DB_BASE_URL="${DATABASE_URL%/*}"
export DATABASE_URL="${TEST_DB_BASE_URL}/${TEST_DB_NAME}"

# Sweep databases orphaned by a previous run's container being SIGKILLed
# before its own cleanup() could fire (e.g. a CI job cancellation). This is a
# deliberate exception to "a run never drops a database it did not create"
# (see TEST_DB_CREATED below): it is safe because it only ever targets
# kendo_test_*-prefixed databases with zero live connections, and every
# concurrently running run holds a sentinel connection to its own database for
# its whole life (see `scratch hold` below) — so no still-running run's
# database can be selected. That sentinel is load-bearing, not decorative: the
# app itself is not connected for most of a run's startup, so without it this
# sweep could drop a starting run's database. The sweep also requires a
# database to look orphaned in two observations a couple of seconds apart,
# which covers the sliver before the sentinel attaches. A failed sweep is a
# nuisance, not a reason to fail the whole run, so it only warns.
if ! SCRATCH_DB_BASE_URL="$TEST_DB_BASE_URL" python -m app.db.scratch sweep; then
    echo "WARNING: startup sweep of orphaned test databases failed — continuing anyway" >&2
fi

# cleanup() must never drop a database this run did not create — see the
# collision note above. Only a successful CREATE flips this to 1.
TEST_DB_CREATED=0

SCRATCH_DB_BASE_URL="$TEST_DB_BASE_URL" SCRATCH_DB_NAME="$TEST_DB_NAME" \
    python -m app.db.scratch create
TEST_DB_CREATED=1

# Hold one connection open to this run's database for as long as the run lives.
# The startup sweep above spares any kendo_test_* database that has a backend in
# pg_stat_activity, and this is what guarantees ours has one. Without it the
# sweep's safety rule rests on the app happening to be connected, which it is
# not for most of a run's startup: /health does no database I/O, app.db.engine's
# engine is lazy, and app.db.bootstrap disposes the engine it migrates on. That
# leaves the database genuinely connectionless from CREATE until the first
# database-touching test — through two 30s readiness gates — and a concurrent
# run's sweep landing in that window would drop it, which is #316 all over again.
SCRATCH_DB_BASE_URL="$TEST_DB_BASE_URL" SCRATCH_DB_NAME="$TEST_DB_NAME" \
    python -m app.db.scratch hold &
DB_HOLD_PID=$!

# Migrate the fresh per-run database. uvicorn's lifespan no longer does this
# (#391) — the app does not own `alembic upgrade head` any more — so the
# harness has to, before uvicorn or pytest touches the schema.
python -m app.db.bootstrap

# Start backend API server. Deliberately outside the BACKEND_ONLY guard: not
# every non-e2e test is server-free — tests/test_auth_begin_calibration.py
# drives http://localhost:8000 directly — so the backend half of the harness
# has to come up in both modes.
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start Vite dev server
if [[ "$BACKEND_ONLY" != "1" ]]; then
    cd /frontend
    npm run dev -- --host 0.0.0.0 --port 5173 &
    FRONTEND_PID=$!
fi

cleanup() {
    # Release the sentinel connection along with the servers. Dropping would
    # survive it either way — drop_database terminates remaining backends — but
    # killing it here keeps the drop's terminate step for genuine surprises.
    kill "$BACKEND_PID" "${FRONTEND_PID:-}" "${DB_HOLD_PID:-}" 2>/dev/null || true
    # Drop the per-run database on every exit path (success or failure) so
    # nothing is left behind for the next invocation to collide with.
    if [[ "${TEST_DB_CREATED:-0}" -ne 1 ]]; then
        return
    fi
    # Report a failed drop rather than swallowing it: a per-run database that
    # silently leaks accumulates on the shared server and quietly defeats the
    # isolation this script exists to provide. Never aborts — cleanup also runs
    # on the failure path, where the original error matters more.
    #
    # `cd /app` in a subshell because cleanup() runs with whatever the current
    # directory happens to be AT EXIT, not at definition: the script cds to
    # /frontend to start Vite and does not cd back until just before pytest, so
    # any exit in between — an ordinary readiness-gate `exit 1`, not just a
    # signal — would otherwise run `python -m app.db.scratch` from /frontend,
    # where the `app` package is not importable. Observed: ModuleNotFoundError,
    # a warning, and a leaked database. The heredoc this replaced was
    # self-contained and had no such dependency, so the fragility came in with
    # the module. The subshell keeps the cd from leaking back to the caller.
    if ! (cd /app && SCRATCH_DB_BASE_URL="$TEST_DB_BASE_URL" \
        SCRATCH_DB_NAME="$TEST_DB_NAME" python -m app.db.scratch drop)
    then
        echo "WARNING: could not drop per-run database '$TEST_DB_NAME' — it has been left behind" >&2
    fi
}
trap cleanup EXIT

echo "Waiting for backend on :8000..."
for i in $(seq 1 30); do
    curl -sf http://localhost:8000/health >/dev/null && break
    sleep 1
done

# The loop above exits after ~30s whether or not the backend ever answered —
# its outcome was previously discarded, so pytest would run against a
# half-migrated database and fail with a wall of unrelated-looking errors
# (e.g. UndefinedTableError) instead of a clear message (#316). Re-check here
# and bail out before wasting time waiting on the frontend too.
#
# --max-time bounds the gate itself: a server that accepts the connection but
# never answers would otherwise hang curl here indefinitely, turning a clear
# failure back into an unexplained CI timeout with no diagnostic — the same
# confusing-failure class this gate exists to remove. The loop bodies above
# deliberately keep no timeout: they run 30 times, so bounding each attempt
# would stretch the worst-case wait from ~30s to minutes, and the readiness
# budget is a separate question (still open on #316).
if ! curl -sf --max-time 5 http://localhost:8000/health >/dev/null; then
    echo "ERROR: backend never became ready on :8000 — aborting before running tests" >&2
    exit 1
fi

if [[ "$BACKEND_ONLY" != "1" ]]; then
    echo "Waiting for frontend on :5173..."
    for i in $(seq 1 30); do
        curl -sf http://localhost:5173 >/dev/null && break
        sleep 1
    done

    # Same reasoning as the backend gate above (#316): confirm the frontend is
    # actually serving before handing off to pytest. Nothing serves :5173 in
    # BACKEND_ONLY mode, so this gate would abort every such run.
    if ! curl -sf --max-time 5 http://localhost:5173 >/dev/null; then
        echo "ERROR: frontend never became ready on :5173 — aborting before running tests" >&2
        exit 1
    fi
fi

echo "Servers ready — running tests"
cd /app
# No -x: a full run reports on the whole suite, so a passing run is evidence
# and a failing run names every problem at once (see #221). Fail-fast is still
# available on demand — see PYTEST_ARGS below.
#
# PYTEST_TARGET overrides which paths are collected (default: the whole suite),
# so a single file can be exercised without editing this script, e.g.
#   podman-compose -f docker-compose.test.yml run --rm \
#     -e PYTEST_TARGET=tests/test_e2e_settings.py test
#
# PYTEST_ARGS passes extra flags to pytest, e.g.
#   podman-compose -f docker-compose.test.yml run --rm -e PYTEST_ARGS=-x test
#
# Flags cannot be passed positionally on the primary runtime: podman-compose
# treats anything after the service name as the container command, so
# `run --rm test -x` fails with `crun: executable file '-x' not found in
# $PATH`. Only real `docker compose` forwards them into "$@" (#284). An env
# var works identically on both, so PYTEST_ARGS is the documented route;
# "$@" is still honoured for anyone on Docker.
#
# Both variables interpolate unquoted so multiple space-separated values
# word-split into separate arguments. That also means the shell glob-expands
# any value containing * ? [ ] against /app — keep values free of those
# characters.
#
# Deliberately NOT `exec pytest`: exec replaces this shell's process image and
# discards its traps with it, so `trap cleanup EXIT` would never fire and the
# per-run database would leak on every single run (#316 — observed leaking
# three databases across three clean runs before this was caught). Run pytest
# as a child instead, then exit with its status so cleanup() runs in between
# and a failing suite still fails the container.
#
# BACKEND_ONLY additionally drops the Playwright files from collection (#336).
# It goes in an array rather than into PYTEST_ARGS because the pattern contains
# a `*`, and PYTEST_ARGS interpolates unquoted — the glob would be expanded
# against /app before pytest ever saw it.
BACKEND_ONLY_ARGS=()
if [[ "$BACKEND_ONLY" == "1" ]]; then
    BACKEND_ONLY_ARGS=(--ignore-glob="tests/test_e2e_*.py")
fi

# PYTEST_MARK is a marker expression, e.g. "not timing_sensitive". It needs the
# same array treatment as BACKEND_ONLY_ARGS for the same reason: a marker
# expression contains spaces, and PYTEST_ARGS interpolates unquoted, so passing
# one through PYTEST_ARGS would split it into separate words and pytest would
# see `-m not` followed by a stray argument.
MARK_ARGS=()
if [[ -n "${PYTEST_MARK:-}" ]]; then
    MARK_ARGS=(-m "$PYTEST_MARK")
fi

set +e
pytest ${PYTEST_TARGET:-tests/} -q ${PYTEST_ARGS:-} "${BACKEND_ONLY_ARGS[@]}" "${MARK_ARGS[@]}" "$@"
PYTEST_STATUS=$?
set -e
exit "$PYTEST_STATUS"
