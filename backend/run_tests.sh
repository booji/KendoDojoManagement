#!/usr/bin/env bash
# Starts backend + frontend servers, then runs the full test suite.
# Used as the entrypoint for docker-compose.test.yml.
set -euo pipefail

# Install frontend dependencies
cd /frontend
npm ci --prefer-offline

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
# the per-run name and create it before anything connects. python3 (with
# asyncpg, already a dependency of the app) does the actual DDL rather than
# shelling out to a psql/createdb client this image doesn't install.
TEST_DB_BASE_URL="${DATABASE_URL%/*}"
export DATABASE_URL="${TEST_DB_BASE_URL}/${TEST_DB_NAME}"

# cleanup() must never drop a database this run did not create — see the
# collision note above. Only a successful CREATE flips this to 1.
TEST_DB_CREATED=0

TEST_DB_NAME="$TEST_DB_NAME" TEST_DB_BASE_URL="$TEST_DB_BASE_URL" python3 - <<'PYEOF'
import asyncio
import os
import re

import asyncpg

# Read the DSN from the environment, not argv: /proc/<pid>/cmdline is readable
# by anything in the same PID namespace and the DSN carries the DB password.
db_name, base_url = os.environ["TEST_DB_NAME"], os.environ["TEST_DB_BASE_URL"]
if not re.fullmatch(r"[A-Za-z0-9_]+", db_name):
    raise SystemExit(f"refusing unsafe database name: {db_name!r}")
maint_dsn = base_url.replace("postgresql+asyncpg://", "postgresql://") + "/postgres"


async def _create() -> None:
    conn = await asyncpg.connect(maint_dsn)
    try:
        # CREATE DATABASE cannot run inside a transaction block; asyncpg does
        # not implicitly wrap a bare execute() in one, so this is safe as-is.
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


asyncio.run(_create())
PYEOF
TEST_DB_CREATED=1

# Start backend API server
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start Vite dev server
cd /frontend
npm run dev -- --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!

cleanup() {
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    # Drop the per-run database on every exit path (success or failure) so
    # nothing is left behind for the next invocation to collide with.
    if [[ "${TEST_DB_CREATED:-0}" -ne 1 ]]; then
        return
    fi
    # Report a failed drop rather than swallowing it: a per-run database that
    # silently leaks accumulates on the shared server and quietly defeats the
    # isolation this script exists to provide. Never aborts — cleanup also runs
    # on the failure path, where the original error matters more.
    if ! TEST_DB_NAME="$TEST_DB_NAME" TEST_DB_BASE_URL="$TEST_DB_BASE_URL" python3 - <<'PYEOF'
import asyncio
import os
import re

import asyncpg

# Read the DSN from the environment, not argv: /proc/<pid>/cmdline is readable
# by anything in the same PID namespace and the DSN carries the DB password.
db_name, base_url = os.environ["TEST_DB_NAME"], os.environ["TEST_DB_BASE_URL"]
if not re.fullmatch(r"[A-Za-z0-9_]+", db_name):
    raise SystemExit(f"refusing unsafe database name: {db_name!r}")
maint_dsn = base_url.replace("postgresql+asyncpg://", "postgresql://") + "/postgres"


async def _drop() -> None:
    conn = await asyncpg.connect(maint_dsn)
    try:
        await conn.execute(f'ALTER DATABASE "{db_name}" WITH ALLOW_CONNECTIONS false')
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            db_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        await conn.close()


asyncio.run(_drop())
PYEOF
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

echo "Waiting for frontend on :5173..."
for i in $(seq 1 30); do
    curl -sf http://localhost:5173 >/dev/null && break
    sleep 1
done

# Same reasoning as the backend gate above (#316): confirm the frontend is
# actually serving before handing off to pytest.
if ! curl -sf --max-time 5 http://localhost:5173 >/dev/null; then
    echo "ERROR: frontend never became ready on :5173 — aborting before running tests" >&2
    exit 1
fi

echo "Both servers ready — running tests"
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
set +e
pytest ${PYTEST_TARGET:-tests/} -q ${PYTEST_ARGS:-} "$@"
PYTEST_STATUS=$?
set -e
exit "$PYTEST_STATUS"
