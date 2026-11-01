"""
File-based tests for the release supply chain (#457).

Installs follow the image's major tag (ADR-0004), so whatever the release
workflow publishes, every install runs on its next restart. These guard the
inputs to that workflow. Everything here inspects files on disk.
"""

import os
import re
from pathlib import Path

import yaml

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
AUDIT = ROOT / ".github" / "workflows" / "audit.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _steps(workflow: Path) -> list[dict]:
    jobs = _load(workflow)["jobs"]
    return [step for job in jobs.values() for step in job.get("steps", [])]


def test_every_action_is_pinned_by_commit_sha():
    # A tag can be moved to malicious code (tj-actions/changed-files, 2025);
    # a commit SHA cannot. The comment names the version for Dependabot and
    # for humans.
    pinned = re.compile(r"^\s*-?\s*uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d")
    unpinned = [
        f"{w.name}: {line.strip()}"
        for w in WORKFLOWS
        for line in w.read_text().splitlines()
        if re.match(r"^\s*-?\s*uses:", line) and not pinned.match(line)
    ]
    assert (
        WORKFLOWS and not unpinned
    ), f"pin these actions by full commit SHA with '# vX.Y.Z': {unpinned}"


def test_dependabot_watches_the_dependency_manifests():
    config = _load(ROOT / ".github" / "dependabot.yml")
    watched = {
        (u["package-ecosystem"], d)
        for u in config["updates"]
        for d in u.get("directories", [u.get("directory")])
    }
    expected = {
        ("github-actions", "/"),
        ("pip", "/backend"),
        ("pip", "/"),  # requirements-docs.txt, installed by docs.yml
        ("npm", "/frontend"),
        ("docker", "/"),
    }
    assert expected <= watched, f"Dependabot does not watch {expected - watched}"


def test_release_signs_the_pushed_digest_keylessly():
    # Signing the digest, not a tag, covers every tag pointing at it and
    # cannot be swapped by retagging. Keyless: the identity is this workflow's
    # OIDC token, so id-token: write, and there is no signing key to steal.
    assert _load(RELEASE)["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
    }
    steps = _steps(RELEASE)
    [build] = [s for s in steps if "build-push-action" in s.get("uses", "")]
    [sign] = [s for s in steps if "cosign sign" in s.get("run", "")]
    assert steps.index(sign) > steps.index(
        build
    ), "cosign can only sign a digest that has already been pushed"
    assert f"steps.{build['id']}.outputs.digest" in str(
        sign.get("env")
    ), "sign the digest build-push-action pushed, not a tag"


def test_dependency_audit_findings_fail_the_job():
    # A finding turns the run red. Nothing gates on it: a fresh advisory in a
    # transitive dependency must not block an urgent release (#457).
    assert "schedule" in _load(AUDIT)[True], (
        "advisories are published without a push; the audit must also run on "
        "a schedule"
    )
    runs = " ".join(s.get("run", "") for s in _steps(AUDIT))
    assert "pip-audit" in runs and "backend/requirements.txt" in runs, runs
    assert "npm audit --omit=dev" in runs, runs
    assert (
        "continue-on-error" not in AUDIT.read_text()
    ), "a finding must fail the audit job, not be soft-failed"


def test_every_workflow_defaults_to_read_only():
    # A job that needs more asks for it itself (docs.yml's deploy). Only the
    # release workflow, which is nothing but its publish job, writes at the top.
    loose = {
        w.name: perms
        for w in WORKFLOWS
        if w != RELEASE
        and (perms := _load(w).get("permissions")) != {"contents": "read"}
    }
    assert not loose, f"top-level permissions must be contents: read: {loose}"
