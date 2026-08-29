---
name: verify
description: Run the full backend + e2e test suite in the PostgreSQL test container and report results.
---

# Verify

Run the full suite and report what happened. From the repo root:

```bash
podman-compose -f docker-compose.test.yml run --rm test
```

Tests only ever run in a container. `backend/tests/conftest.py` refuses to
collect unless `DATABASE_URL` is a PostgreSQL URL naming a database whose name
contains "test", so a bare `pytest` on the host fails at import with a
`RuntimeError` before a single test runs.

A full run takes ~11 minutes. Redirect it to a file rather than piping through
`tail` — the summary line is what you need and it is easy to truncate away.

## Scoping a run

```bash
# One file or directory
podman-compose -f docker-compose.test.yml run --rm \
  -e PYTEST_TARGET=tests/test_members.py test

# Extra pytest flags, e.g. fail-fast while iterating
podman-compose -f docker-compose.test.yml run --rm -e PYTEST_ARGS=-x test
```

Flags go through `PYTEST_ARGS`, **not** positionally after the service name:
`podman-compose` treats trailing arguments as the container command, so
``run --rm test -x`` fails with ``crun: executable file `-x` not found in
$PATH``. `PYTEST_ARGS` interpolates unquoted, so keep values free of `*`, `?`
and `[]` — the shell would glob-expand them against `/app`.

**Never pass `--entrypoint bash`.** The entrypoint is `backend/run_tests.sh`,
which installs frontend deps and starts uvicorn (:8000) and Vite (:5173) before
invoking pytest; the Playwright e2e tests drive those servers. Skipping it makes
every `test_e2e_*` test fail with connection-refused, which looks like a large
regression but is only a misconfigured run. For backend-only tests, keep the
entrypoint and set `PYTEST_TARGET`, or add `--ignore-glob='tests/test_e2e_*.py'`.

## Report

- Pass/fail summary
- Any failing test names and their error output
- Whether all tests passed or action is needed
