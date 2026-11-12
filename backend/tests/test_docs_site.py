"""File-based tests for the docs site (issue #415).

MkDocs Material on GitHub Pages, one version per major image tag via mike, so
an operator on `:1` reads the `1.x` docs. What is pinned here is what a broken
docs build would not show on its own: which version a ref publishes to, that a
pull request only ever builds, and that the nav names pages that exist (the
backend suite runs on pushes the docs workflow's path filter skips).

Everything here inspects files on disk — no MkDocs, no GitHub API.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.deploy_contract import PUBLISHED_IMAGE, RELEASE_PIN

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)
WORKFLOW = ROOT / ".github" / "workflows" / "docs.yml"
MKDOCS = ROOT / "mkdocs.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _steps() -> list[dict]:
    return [step for job in _workflow()["jobs"].values() for step in job["steps"]]


def _version_for(ref: str, tmp_path: Path) -> str:
    """Run the workflow's own version step for REF and return its output."""
    [step] = [s for s in _steps() if s.get("id") == "version"]
    out = tmp_path / "github_output"
    out.touch()
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        env={**os.environ, "GITHUB_REF": ref, "GITHUB_OUTPUT": str(out)},
        check=True,
    )
    lines = dict(line.split("=", 1) for line in out.read_text().splitlines())
    return lines["version"]


@pytest.mark.parametrize(
    ("ref", "version"),
    [
        ("refs/tags/v1.4.0", "1.x"),
        ("refs/tags/v2.0.0", "2.x"),
        # Before 1.0 the image pin is :0.Y (ADR-0009), so the docs are too.
        ("refs/tags/v0.3.1", "0.3.x"),
        ("refs/tags/v0.1.0", "0.1.x"),
        # dev tracks the integration branch; main only moves on a release.
        ("refs/heads/develop", "dev"),
        ("refs/heads/main", ""),
        # A release candidate's image gets only its exact tag, never :1 — so
        # there is no 1.x for its docs to update either.
        ("refs/tags/v1.0.0-rc1", ""),
        ("refs/tags/v0.1.0-rc1", ""),
    ],
)
def test_each_ref_publishes_the_docs_version_its_image_tag_implies(
    ref, version, tmp_path
):
    assert _version_for(ref, tmp_path) == version


def test_a_pull_request_builds_strict_and_never_deploys():
    workflow = _workflow()
    assert "pull_request" in workflow[True]  # PyYAML reads `on:` as True
    assert any("mkdocs build --strict" in s.get("run", "") for s in _steps())
    for name, job in workflow["jobs"].items():
        if any("mike" in s.get("run", "") for s in job["steps"]):
            assert "github.event_name == 'push'" in job.get("if", ""), name


def test_dev_docs_publish_from_develop():
    workflow = _workflow()
    assert workflow[True]["push"]["branches"] == ["develop"]
    [deploy] = [
        job
        for job in workflow["jobs"].values()
        if any("mike" in s.get("run", "") for s in job["steps"])
    ]
    assert "refs/heads/main" not in deploy["if"], deploy["if"]


def _nav_pages(nav) -> list[str]:
    if isinstance(nav, str):
        return [nav]
    if isinstance(nav, list):
        return [p for item in nav for p in _nav_pages(item)]
    return [p for value in nav.values() for p in _nav_pages(value)]


def test_every_page_in_the_nav_exists():
    nav = yaml.safe_load(MKDOCS.read_text())["nav"]
    pages = _nav_pages(nav)
    assert pages
    missing = [p for p in pages if not (ROOT / "docs" / p).is_file()]
    assert not missing, missing


def test_operator_docs_name_only_the_current_pin():
    """Every page names the pin the bundle does: a new Release line moves it
    everywhere at once, so the docs published for each line show that line's
    pin (ADR-0009)."""
    pages = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]
    pins = {
        (page.relative_to(ROOT).as_posix(), f"{PUBLISHED_IMAGE}:{tag}")
        for page in pages
        for tag in re.findall(
            rf"{re.escape(PUBLISHED_IMAGE)}:([\w.-]+)", page.read_text()
        )
    }
    assert pins
    assert {pin for _, pin in pins} == {RELEASE_PIN}, sorted(pins)


def test_every_machinectl_shell_names_the_shell_to_run():
    """`kendo` logs in to /usr/sbin/nologin, on purpose, and `machinectl shell`
    starts the login shell unless told otherwise: a bare `machinectl shell
    kendo@` ends at once with "This account is currently not available" (#576).
    """
    sources = [ROOT / "README.md", ROOT / "setup.sh", *(ROOT / "docs").rglob("*.md")]
    bare = [
        (src.relative_to(ROOT).as_posix(), line.strip())
        for src in sources
        for line in src.read_text().splitlines()
        if re.search(r"machinectl shell kendo@(?! /bin/bash)", line)
    ]
    assert not bare, bare
