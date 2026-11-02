"""
The licence file and every place that names the licence agree (#390).

Without a LICENSE nobody may legally run, fork or redistribute the project,
and package metadata that names a different licence contradicts the file.
"""

import json
import os
import tomllib
from pathlib import Path

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)
SPDX = "AGPL-3.0-or-later"


def test_the_licence_is_agpl_3_or_later_everywhere_it_is_named():
    licence = (ROOT / "LICENSE").read_text()
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in licence
    assert "Version 3, 19 November 2007" in licence

    pyproject = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text())
    package = json.loads((ROOT / "frontend" / "package.json").read_text())
    assert pyproject["project"]["license"] == SPDX
    assert package["license"] == SPDX
    assert SPDX in (ROOT / "README.md").read_text()


def test_the_published_image_is_labelled_with_the_same_licence():
    # docker/metadata-action otherwise derives the label from the licence
    # GitHub detects, which is the bare AGPL-3.0, not -or-later.
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert f"org.opencontainers.image.licenses={SPDX}" in release
