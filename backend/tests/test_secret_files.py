"""Secrets delivered as mounted files rather than environment variables (#462).

An environment variable shows up in `podman inspect` and /proc/<pid>/environ
and is inherited by every child process, so production mounts each secret as a
file and names it in `<NAME>_FILE`. The plain `<NAME>` variable stays as the
fallback the dev and test stacks use.
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

import app.config as config


def test_file_wins_over_the_variable(tmp_path, monkeypatch):
    secret = tmp_path / "jwt_secret"
    secret.write_text("from-the-file")
    monkeypatch.setenv("JWT_SECRET", "from-the-environment")
    monkeypatch.setenv("JWT_SECRET_FILE", str(secret))

    assert config.read_secret("JWT_SECRET") == "from-the-file"


def test_a_trailing_newline_in_the_file_is_not_part_of_the_secret(
    tmp_path, monkeypatch
):
    # `echo token > file` and most editors end the file with a newline.
    secret = tmp_path / "setup_token"
    secret.write_text("the-token\n")
    monkeypatch.setenv("SETUP_TOKEN_FILE", str(secret))

    assert config.read_secret("SETUP_TOKEN") == "the-token"


def test_an_unreadable_file_fails_naming_the_variable_not_as_a_blank_secret(
    tmp_path, monkeypatch
):
    # Falling back to the variable, or to "", would surface as "JWT_SECRET
    # must be set" and send the operator looking in the wrong place.
    monkeypatch.setenv("JWT_SECRET_FILE", str(tmp_path / "missing"))

    with pytest.raises(RuntimeError, match="JWT_SECRET_FILE"):
        config.read_secret("JWT_SECRET")


@pytest.mark.parametrize(
    "name", ["DATABASE_URL", "MIGRATION_DATABASE_URL", "JWT_SECRET", "SETUP_TOKEN"]
)
def test_each_secret_setting_is_read_from_its_file(name, tmp_path, monkeypatch):
    secret = tmp_path / name.lower()
    secret.write_text(f"{name}-from-the-file")
    monkeypatch.setenv(name, "from-the-environment")
    monkeypatch.setenv(f"{name}_FILE", str(secret))

    try:
        reloaded = importlib.reload(config)
        assert getattr(reloaded, name) == f"{name}-from-the-file"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_alembic_reads_the_database_url_file(tmp_path):
    """`podman exec kendo-app alembic ...` (docs/install/upgrading.md) runs
    where only DATABASE_URL_FILE is set. Without it alembic.ini's placeholder
    URL is used and the command fails."""
    url_file = tmp_path / "database_url"
    url_file.write_text(os.environ["DATABASE_URL"])
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["DATABASE_URL_FILE"] = str(url_file)

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
