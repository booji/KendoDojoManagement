"""
File-based tests for the CI split introduced by issue #336.

The repository is private, so Actions minutes are metered, and the full suite
is ~15 minutes almost entirely because of the 50-odd Playwright e2e files.
Firing the whole thing on every push would spend the monthly allowance on
signal a much cheaper job already gives. The split is:

  * a backend-only job on every push — light image, no Vite, no browsers;
  * the existing full suite, unchanged, on release tags and dispatch.

Everything here inspects files on disk — no Docker, no GitHub API.
"""

import os
from pathlib import Path

import yaml

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
TEST_COMPOSE_FILE = ROOT / "docker-compose.test.yml"
DOCKERFILE = ROOT / "Dockerfile"
WORKFLOWS = ROOT / ".github" / "workflows"
FULL_SUITE_WORKFLOW = WORKFLOWS / "tests.yml"
BACKEND_WORKFLOW = WORKFLOWS / "backend-tests.yml"

BACKEND_SERVICE = "test-backend"


def _load(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def _backend_service() -> dict:
    services = _load(TEST_COMPOSE_FILE)["services"]
    assert BACKEND_SERVICE in services, (
        f"docker-compose.test.yml must define a '{BACKEND_SERVICE}' service for "
        "the backend-only CI job"
    )
    return services[BACKEND_SERVICE]


# ---------------------------------------------------------------------------
# The backend-only compose service
# ---------------------------------------------------------------------------


def test_backend_service_runs_in_backend_only_mode():
    environment = _backend_service().get("environment", {})
    assert str(environment.get("BACKEND_ONLY")) == "1", (
        f"the '{BACKEND_SERVICE}' service must set BACKEND_ONLY=1 so "
        "run_tests.sh skips the frontend install, Vite and e2e collection"
    )


def test_backend_service_builds_the_image_without_playwright():
    """
    The saving is only real if the *image* is light too. `backend-e2e-deps`
    adds a NodeSource install and `playwright install --with-deps chromium` on
    top of `backend-dev-deps`; CI has no layer cache, so building it would cost
    minutes before a single test ran.
    """
    target = _backend_service().get("build", {}).get("target")
    assert target == "backend-dev-deps", (
        f"the '{BACKEND_SERVICE}' service must build the backend-dev-deps "
        f"stage, not the Playwright-carrying e2e stage; got {target!r}"
    )


def test_backend_service_keeps_the_run_tests_entrypoint():
    """
    CLAUDE.md: the compose entrypoint must stay backend/run_tests.sh. It owns
    the per-run throwaway database (#316), so bypassing it to call pytest
    directly loses the database the tests connect to.
    """
    command = _backend_service().get("command")
    assert command and "run_tests.sh" in str(command), (
        f"the '{BACKEND_SERVICE}' service must run run_tests.sh, not pytest "
        f"directly; got {command!r}"
    )


def test_backend_service_waits_for_a_healthy_database():
    depends_on = _backend_service().get("depends_on", {})
    assert depends_on.get("db", {}).get("condition") == "service_healthy", (
        f"the '{BACKEND_SERVICE}' service must wait for the db service to be "
        "healthy, like the full-suite service does"
    )


def test_backend_dev_deps_stage_provides_curl():
    """
    run_tests.sh gates on `curl -sf http://localhost:8000/health` before
    handing off to pytest (#316). curl arrives in the e2e stage today, so the
    lighter stage has to carry it or every backend-only run aborts at the gate.
    """
    text = DOCKERFILE.read_text()
    dev_stage = text.split("AS backend-dev-deps", 1)[1].split("FROM ", 1)[0]
    assert "curl" in dev_stage, (
        "the backend-dev-deps stage must install curl — run_tests.sh's :8000 "
        "readiness gate uses it, and BACKEND_ONLY runs build this stage"
    )


# ---------------------------------------------------------------------------
# The workflows
# ---------------------------------------------------------------------------


def test_backend_workflow_runs_on_every_push():
    # PyYAML parses the bare key `on` as the boolean True (YAML 1.1).
    triggers = _load(BACKEND_WORKFLOW)[True]
    assert "push" in triggers, (
        "the backend-only workflow must trigger on push — per-change signal is "
        "the whole point of the split"
    )


def test_backend_workflow_skips_documentation_only_changes():
    """Option C: nothing spent on a README typo."""
    paths_ignore = _load(BACKEND_WORKFLOW)[True]["push"].get("paths-ignore", [])
    assert "**.md" in paths_ignore and "docs/**" in paths_ignore, (
        "the backend-only workflow must carry paths-ignore for '**.md' and "
        f"'docs/**'; got {paths_ignore!r}"
    )


def test_backend_workflow_invokes_the_backend_only_service():
    text = BACKEND_WORKFLOW.read_text()
    assert BACKEND_SERVICE in text, (
        f"the backend-only workflow must run the '{BACKEND_SERVICE}' compose service"
    )


def test_backend_workflow_is_least_privilege():
    permissions = _load(BACKEND_WORKFLOW).get("permissions", {})
    assert permissions == {"contents": "read"}, (
        "the backend-only workflow only ever reads the checked-out tree; "
        f"got {permissions!r}"
    )


def test_backend_workflow_cancels_superseded_runs():
    """Pushing three times in a minute should bill for one run, not three."""
    concurrency = _load(BACKEND_WORKFLOW).get("concurrency", {})
    assert concurrency.get("cancel-in-progress") is True, (
        "the backend-only workflow must cancel superseded runs, like the "
        "full-suite workflow does"
    )


def test_backend_workflow_runs_on_pull_requests():
    """A fork's branch pushes never reach this repository's Actions, so a fork
    PR into develop only gets CI from a pull_request trigger (#549)."""
    triggers = _load(BACKEND_WORKFLOW)[True]
    assert "pull_request" in triggers, triggers
    paths_ignore = (triggers["pull_request"] or {}).get("paths-ignore", [])
    assert "**.md" in paths_ignore and "docs/**" in paths_ignore, paths_ignore


def test_full_suite_workflow_runs_on_release_candidates_and_prs_into_main():
    """
    Regression guard: the full suite runs where a release is cut, not on every
    push. Release and hotfix PRs into main need it as a required check (#549);
    everything else stays on the backend-only job.
    """
    triggers = _load(FULL_SUITE_WORKFLOW)[True]
    assert triggers["pull_request"] == {"branches": ["main"]}, triggers
    assert triggers["push"] == {"tags": ["v*-rc*"]}, (
        f"the full suite must stay on release-candidate tags; got {triggers['push']!r}"
    )


def test_release_notes_lead_with_what_an_operator_must_act_on():
    """Generated release notes group by label (#548): a Breaking change first,
    then security, then features and fixes, then everything else."""
    categories = _load(ROOT / ".github" / "release.yml")["changelog"]["categories"]
    assert [c["labels"] for c in categories] == [
        ["breaking"],
        ["security"],
        ["feature"],
        ["bug"],
        ["*"],
    ], categories
    assert categories[0]["title"] == "Breaking / Operator action", categories
