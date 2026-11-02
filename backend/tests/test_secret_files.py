"""Secrets delivered as mounted files rather than environment variables (#462).

Production mounts each secret as a file and names it in `<NAME>_FILE` (why: see
read_secret in app/config.py). The plain `<NAME>` variable stays as the
fallback the dev and test stacks use.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import app.config as config
from tests.deploy_contract import ALL_SECRETS


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


def test_each_secret_setting_is_read_from_its_file(tmp_path):
    # app.config resolves its settings once, at import: import it afresh in a
    # child process rather than rebinding this process's module globals.
    env = dict(os.environ)
    for name in ALL_SECRETS:
        (tmp_path / name).write_text(f"{name}-from-the-file")
        env[name] = "from-the-environment"
        env[f"{name}_FILE"] = str(tmp_path / name)
    code = (
        "import json, sys, app.config as c; "
        "print(json.dumps({n: getattr(c, n) for n in sys.argv[1:]}))"
    )

    result = subprocess.run(
        [sys.executable, "-c", code, *ALL_SECRETS],
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == {n: f"{n}-from-the-file" for n in ALL_SECRETS}


_UNREACHABLE_URL = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"


@pytest.mark.parametrize(
    "variable", [None, _UNREACHABLE_URL], ids=["file-only", "file-and-variable"]
)
def test_alembic_reads_the_database_url_file(tmp_path, variable):
    """Alembic run by hand in the app container (`podman exec kendo-app
    alembic current`; no operator doc prescribes it since the pre-0.1 upgrade
    notes went) sees DATABASE_URL_FILE. The file wins over the variable, as it
    does for the app: one rule, read_secret's."""
    url_file = tmp_path / "database_url"
    url_file.write_text(os.environ["DATABASE_URL"])
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["DATABASE_URL_FILE"] = str(url_file)
    if variable is not None:
        env["DATABASE_URL"] = variable

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_migrations_ignore_the_app_login_the_environment_names(tmp_path, monkeypatch):
    """ADR-0007: migrations run as the superuser login bootstrap is handed, even
    in kendo-migrate, where DATABASE_URL_FILE names the app user's login. A
    migration run as the app user would fail on its first CREATE."""
    from alembic import command
    from app.db.bootstrap import _alembic_config

    migration_url = os.environ["DATABASE_URL"]
    app_login = tmp_path / "database_url"
    app_login.write_text(_UNREACHABLE_URL)
    monkeypatch.setenv("DATABASE_URL", _UNREACHABLE_URL)
    monkeypatch.setenv("DATABASE_URL_FILE", str(app_login))

    command.current(_alembic_config(migration_url))  # connects, or raises
