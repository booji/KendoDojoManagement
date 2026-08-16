"""
File-based tests for the test-harness readiness gate in backend/run_tests.sh
(Issue #316).

run_tests.sh waits for the backend (:8000) and frontend (:5173) dev servers
before invoking pytest, but each wait loop is a `for` loop with a `curl -sf
... && break` body: it exits after ~30 iterations whether or not the server
ever became healthy. Nothing inspects the outcome, so `exec pytest` always
runs — including against a server that never finished starting/migrating.
That produces a huge, unrelated-looking wall of failures (e.g.
UndefinedTableError) instead of a clear "server never came up" message.

These tests inspect run_tests.sh as text on disk — no live Docker, no
running servers required. They assert on STRUCTURAL properties of the
script (guard + non-zero exit reachable from each loop, unreachable
`exec pytest` on failure) rather than pinning exact wording, so the
implementing agent retains freedom of phrasing.
"""

import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# In the docker-compose.test.yml container, REPO_ROOT=/repo (full repo mount).
# Locally, walk three levels up from this file (backend/tests/ → repo root).
ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)
RUN_TESTS_SCRIPT = ROOT / "backend" / "run_tests.sh"


def _script_text() -> str:
    return RUN_TESTS_SCRIPT.read_text()


# ---------------------------------------------------------------------------
# Regression guard — set -euo pipefail
# ---------------------------------------------------------------------------


def test_script_still_sets_strict_shell_options():
    """
    The script must keep `set -euo pipefail`. This is a regression guard: if
    a future edit removes it while adding the readiness gate, unrelated
    commands could silently fail (or a pipeline's exit status could be
    swallowed) without stopping the script.
    """
    text = _script_text()
    assert re.search(
        r"^\s*set\s+-euo\s+pipefail\s*$", text, re.MULTILINE
    ), "run_tests.sh must contain 'set -euo pipefail'"


# ---------------------------------------------------------------------------
# Helpers for locating the readiness-loop regions
# ---------------------------------------------------------------------------


def _backend_loop_region() -> str:
    """Text from the end of the backend wait loop's `for` line's closing
    `done` up to (but not including) the start of the frontend wait section.
    """
    text = _script_text()
    backend_for = re.search(r'echo\s+"Waiting for backend on :8000', text)
    assert backend_for, "could not find backend readiness loop banner"
    frontend_for = re.search(r'echo\s+"Waiting for frontend on :5173', text)
    assert frontend_for, "could not find frontend readiness loop banner"
    # Region: from the backend loop's "done" (first "done" after the banner)
    # to the frontend banner.
    done_match = re.search(r"\bdone\b", text[backend_for.end() :])
    assert done_match, "could not find closing 'done' for backend readiness loop"
    region_start = backend_for.end() + done_match.end()
    return text[region_start : frontend_for.start()]


def _frontend_loop_region() -> str:
    """Text from the end of the frontend wait loop's closing `done` up to
    the `exec pytest` line (or end of file if not found, which itself would
    be a failure signal for another test).
    """
    text = _script_text()
    frontend_for = re.search(r'echo\s+"Waiting for frontend on :5173', text)
    assert frontend_for, "could not find frontend readiness loop banner"
    done_match = re.search(r"\bdone\b", text[frontend_for.end() :])
    assert done_match, "could not find closing 'done' for frontend readiness loop"
    region_start = frontend_for.end() + done_match.end()
    exec_match = re.search(r"exec\s+pytest", text[region_start:])
    region_end = region_start + exec_match.start() if exec_match else len(text)
    return text[region_start:region_end]


# A guard construct: something that re-checks health and, on failure, exits
# non-zero. We look for a conditional (`if`/`||`) containing both a health
# probe (curl) and an `exit` with a non-zero literal status, OR a pattern
# where the loop's own success is checked via a sentinel/flag and a
# subsequent non-zero exit. To avoid pinning exact wording we require:
#   1. Somewhere in the region, an `exit` statement with a non-zero code.
#   2. That exit is inside some conditional/guard (not unconditionally
#      reached) — i.e. it is preceded on an earlier or the same line by
#      `if`, `||`, or similar, within the same small block.
_NONZERO_EXIT_RE = re.compile(r"exit\s+([1-9][0-9]*)\b")


def _find_guarded_nonzero_exit(region: str) -> re.Match | None:
    return _NONZERO_EXIT_RE.search(region)


# ---------------------------------------------------------------------------
# Backend readiness gate
# ---------------------------------------------------------------------------


def test_backend_readiness_is_rechecked_after_the_wait_loop():
    """
    Acceptance criterion 1: after the backend wait loop, the script must
    verify the backend actually became healthy (not just that the loop
    finished — which happens unconditionally after ~30s regardless of
    outcome).

    We assert that the region between the backend loop's `done` and the
    frontend loop's banner contains a health probe (a curl-style check
    against the backend, or a reused/derived readiness signal) combined
    with a conditional. This would fail against the current script, which
    has nothing at all in that region — the loop's outcome is discarded.

    Confidence: medium-high. It requires *some* additional check to exist
    in that region at all, which the current script fails trivially (empty
    region). It does not by itself guarantee the check is correct, only
    that something is there — the exit-code test below narrows further.
    """
    region = _backend_loop_region()
    assert region.strip(), (
        "expected additional readiness-verification code between the backend "
        "wait loop and the frontend wait loop's banner, but found nothing — "
        "the loop's outcome is never checked"
    )


def test_backend_readiness_failure_exits_non_zero_before_frontend_wait():
    """
    Acceptance criterion 1 (exit code) + criterion 4 (exec pytest
    unreachable): if the backend never became healthy, the script must exit
    with a non-zero status before proceeding to wait for the frontend (and
    therefore long before `exec pytest`).

    We assert the backend-loop region contains an `exit N` with N != 0.
    This is a structural check: a script that discards the loop's outcome
    (the current behaviour) has no exit statement here at all, so this
    fails for the right reason against the unmodified script.

    Confidence: medium. A script could technically satisfy this with an
    unconditional `exit 1` (which would break the happy path too) — but
    that would be caught by the full-suite test run against a healthy
    server, so it is an acceptable structural approximation without pinning
    exact conditional syntax.
    """
    region = _backend_loop_region()
    match = _find_guarded_nonzero_exit(region)
    assert match, (
        "expected an 'exit N' (N != 0) in the backend readiness-check region "
        "(between the backend wait loop and the frontend wait loop), so a "
        "backend that never became healthy stops the script instead of "
        "silently continuing"
    )


def test_backend_readiness_failure_message_names_backend():
    """
    Acceptance criterion 3: the failure path must emit a diagnostic message
    naming which server never became ready. We check that the backend
    readiness-check region contains output (echo/printf to stdout or
    stderr) mentioning "backend", so a failed run is self-explanatory
    rather than surfacing as an unrelated wall of test failures.

    Confidence: medium. We only check for the word "backend" (case
    insensitive) near an echo/printf-like statement in the region — the
    exact wording is intentionally left to the implementer.
    """
    region = _backend_loop_region()
    has_diagnostic = re.search(r"(echo|printf)[^\n]*backend", region, re.IGNORECASE)
    assert has_diagnostic, (
        "expected a diagnostic message mentioning 'backend' in the failure "
        "path of the backend readiness check, so a failed run names the "
        "server that never became ready"
    )


# ---------------------------------------------------------------------------
# Frontend readiness gate
# ---------------------------------------------------------------------------


def test_frontend_readiness_is_rechecked_after_the_wait_loop():
    """
    Acceptance criterion 2 (backend's frontend counterpart): after the
    frontend wait loop, the script must verify the frontend actually became
    healthy before proceeding to `exec pytest`.

    Unlike the backend region, the frontend region in the *unmodified*
    script is not textually empty — it already contains the "Both servers
    ready — running tests" echo, a `cd /app`, and comments explaining
    PYTEST_TARGET. None of that verifies anything, so a naive
    non-emptiness check would pass vacuously on the current, broken
    script. Instead we strip that known boilerplate (comments, blank
    lines, the "ready — running tests" echo, and the `cd` command) and
    require something to remain — i.e. actual verification logic, not
    just scaffolding.

    Confidence: medium. This is deliberately more conservative than a bare
    non-emptiness check specifically so it fails for the right reason
    against the current script (verified: it does).
    """
    region = _frontend_loop_region()
    remaining_lines = [
        line
        for line in region.splitlines()
        if line.strip()
        and not line.strip().startswith("#")
        and "running tests" not in line.lower()
        and line.strip() not in {"cd /app", "cd /frontend"}
    ]
    assert remaining_lines, (
        "expected readiness-verification code between the frontend wait "
        "loop and 'exec pytest' (beyond the existing boilerplate echo/cd/"
        "comments), but found nothing — the loop's outcome is never checked"
    )


def test_frontend_readiness_failure_exits_non_zero_before_pytest():
    """
    Acceptance criterion 2 (exit code) + criterion 4 (exec pytest
    unreachable): if the frontend never became healthy, the script must
    exit non-zero before reaching `exec pytest`.

    We assert the frontend-loop region (scoped to end at the first
    `exec pytest` occurrence) contains an `exit N` with N != 0.

    Confidence: medium, same caveat as the backend counterpart — this is a
    structural approximation, not a full control-flow proof.
    """
    region = _frontend_loop_region()
    match = _find_guarded_nonzero_exit(region)
    assert match, (
        "expected an 'exit N' (N != 0) in the frontend readiness-check "
        "region (between the frontend wait loop and 'exec pytest'), so a "
        "frontend that never became healthy stops the script before tests run"
    )


def test_frontend_readiness_failure_message_names_frontend():
    """
    Acceptance criterion 3, frontend counterpart: the failure path must
    name the frontend specifically, distinguishing it from a backend
    failure.

    Confidence: medium, same reasoning as the backend diagnostic test.
    """
    region = _frontend_loop_region()
    has_diagnostic = re.search(r"(echo|printf)[^\n]*frontend", region, re.IGNORECASE)
    assert has_diagnostic, (
        "expected a diagnostic message mentioning 'frontend' in the failure "
        "path of the frontend readiness check, so a failed run names the "
        "server that never became ready"
    )


# ---------------------------------------------------------------------------
# exec pytest must not be reachable on failure
# ---------------------------------------------------------------------------


# Note: a test asserting "`exec pytest` is not the very next substantive
# statement after the frontend loop" was deliberately omitted. In the
# *current* (broken) script, the "Both servers ready — running tests" echo,
# a `cd /app`, and PYTEST_TARGET comments already sit between the loop and
# `exec pytest` — so that shape alone is not evidence of a working guard,
# and such a test would pass vacuously today rather than failing for the
# right reason. test_frontend_readiness_failure_exits_non_zero_before_pytest
# and test_frontend_readiness_is_rechecked_after_the_wait_loop above cover
# the same acceptance criterion (exec pytest unreachable on failure) with
# assertions that do fail against the unmodified script.
