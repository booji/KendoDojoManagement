"""Static contract tests for the Makefile (issue #373).

No container is started — these read the Makefile from the repository mount and
assert the externally-observable contract: which targets exist, what a bare
`make` does, and which Compose stacks a teardown target touches.

The certificate recipe's *behaviour* lives in `deploy/bin/dev-certs.sh` and is
tested by running it — see `test_dev_certs_script.py`. What is left here is the
wiring: that the targets exist and delegate to that script.
"""

import os
import re
from pathlib import Path

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)
MAKEFILE = ROOT / "Makefile"


def makefile_text() -> str:
    return MAKEFILE.read_text()


def _rule_of(target: str) -> tuple[str, list[str]]:
    """The rule for `target` as (prerequisite line, recipe lines)."""
    lines = makefile_text().splitlines()
    for i, line in enumerate(lines):
        match = re.match(rf"^{re.escape(target)}\s*:([^=]*)$", line)
        if not match:
            continue
        recipe = []
        for follow in lines[i + 1 :]:
            if follow.startswith("\t"):
                recipe.append(follow)
            elif follow.strip():
                break
        return match.group(1), recipe
    raise AssertionError(f"no target {target!r} in the Makefile")


def recipe_of(target: str) -> str:
    return "\n".join(_rule_of(target)[1])


def prerequisites_of(target: str) -> list[str]:
    return _rule_of(target)[0].split()


def phony_targets() -> list[str]:
    match = re.search(r"^\.PHONY:(.*)$", makefile_text(), re.M)
    assert match, "the Makefile declares no .PHONY targets"
    return match.group(1).split()


def documented_targets() -> list[str]:
    return re.findall(r"^## (\S+?):", makefile_text(), re.M)


# ---------------------------------------------------------------------------
# A bare `make` starts nothing
# ---------------------------------------------------------------------------


def test_default_goal_is_help():
    assert re.search(r"^\.DEFAULT_GOAL\s*:=\s*help$", makefile_text(), re.M), (
        "a bare `make` must print the target list, not run the first target"
    )


# ---------------------------------------------------------------------------
# Teardown splits: `down` leaves the quick self-host alone
# ---------------------------------------------------------------------------


def test_down_stops_the_dev_and_test_stacks():
    recipe = recipe_of("down")
    assert "COMPOSE_DEV" in recipe
    assert "COMPOSE_TEST" in recipe


def test_down_does_not_touch_the_quick_self_host():
    assert "COMPOSE_PROD" not in recipe_of("down"), (
        "`make down` must not stop the quick self-host — it would take a dojo offline"
    )


def test_a_separately_named_target_stops_the_quick_self_host():
    assert "COMPOSE_PROD" in recipe_of("down-selfhost")


def test_down_does_not_depend_on_the_self_host_teardown():
    assert "down-selfhost" not in prerequisites_of("down")


# ---------------------------------------------------------------------------
# Dev certificates
# ---------------------------------------------------------------------------


def test_certs_is_a_prerequisite_of_dev():
    assert "certs" in prerequisites_of("dev")


def test_cert_directory_is_gitignored():
    ignored = (ROOT / ".gitignore").read_text()
    assert "deploy/certs/" in ignored


def test_certs_delegates_to_the_certificate_script():
    assert "dev-certs.sh" in recipe_of("certs")


def test_a_separately_named_target_forces_a_reissue():
    recipe = recipe_of("certs-force")
    assert "dev-certs.sh" in recipe
    assert "--force" in recipe, "the reissue path must not need a manual `rm`"


def test_the_certificate_script_is_executable():
    script = ROOT / "deploy" / "bin" / "dev-certs.sh"
    assert script.exists()
    assert script.stat().st_mode & 0o111, "`make certs` runs it directly"


# ---------------------------------------------------------------------------
# Help output stays complete
# ---------------------------------------------------------------------------


def test_every_target_has_a_help_description():
    undocumented = sorted(set(phony_targets()) - set(documented_targets()))
    assert not undocumented, (
        f"targets missing a `## name: description` line: {undocumented}"
    )


# ---------------------------------------------------------------------------
# One way to run the app locally
# ---------------------------------------------------------------------------


def test_host_venv_script_is_gone():
    assert not (ROOT / "dev.sh").exists(), (
        "dev.sh is a second, untested way to run the app — the container stack is the only one"
    )
