"""
File-based tests for Production Docker Compose configuration (Issue #5).
No live Docker required — these inspect files on disk.
"""

import os
import re as _re
from pathlib import Path

import pytest
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
COMPOSE_FILE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"
REQUIREMENTS = ROOT / "backend" / "requirements.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_compose() -> dict:
    with COMPOSE_FILE.open() as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# docker-compose.yml — services
# ---------------------------------------------------------------------------


def test_compose_has_app_service():
    compose = load_compose()
    assert "app" in compose.get(
        "services", {}
    ), "docker-compose.yml must define an 'app' service"


def test_compose_has_db_service():
    compose = load_compose()
    assert "db" in compose.get(
        "services", {}
    ), "docker-compose.yml must define a 'db' service"


# ---------------------------------------------------------------------------
# docker-compose.yml — named volume
# ---------------------------------------------------------------------------


def test_compose_has_named_postgres_volume():
    compose = load_compose()
    top_level_volumes = compose.get("volumes", {})
    assert (
        top_level_volumes
    ), "docker-compose.yml must declare at least one named volume"

    db_service = compose["services"]["db"]
    db_volumes = db_service.get("volumes", [])
    volume_names = list(top_level_volumes.keys())

    mounted = any(
        any(vol_name in str(v) for vol_name in volume_names) for v in db_volumes
    )
    assert (
        mounted
    ), "The db service must mount a top-level named volume for postgres data"


# ---------------------------------------------------------------------------
# docker-compose.yml — app service env vars
# ---------------------------------------------------------------------------

REQUIRED_APP_ENV_VARS = [
    "DATABASE_URL",
    "JWT_SECRET",
    "JWT_EXPIRE_MINUTES",
    "COOKIE_SECURE",
]


@pytest.mark.parametrize("var_name", REQUIRED_APP_ENV_VARS)
def test_compose_app_service_env_includes(var_name: str):
    compose = load_compose()
    app_env: dict = compose["services"]["app"].get("environment", {})
    # environment can be a dict or a list of "KEY=VALUE" strings
    if isinstance(app_env, list):
        keys = [entry.split("=")[0] for entry in app_env]
    else:
        keys = list(app_env.keys())
    assert var_name in keys, f"app service environment must include {var_name}"


# ---------------------------------------------------------------------------
# docker-compose.yml — db service env vars
# ---------------------------------------------------------------------------

REQUIRED_DB_ENV_VARS = [
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
]


@pytest.mark.parametrize("var_name", REQUIRED_DB_ENV_VARS)
def test_compose_db_service_env_includes(var_name: str):
    compose = load_compose()
    db_env: dict = compose["services"]["db"].get("environment", {})
    if isinstance(db_env, list):
        keys = [entry.split("=")[0] for entry in db_env]
    else:
        keys = list(db_env.keys())
    assert var_name in keys, f"db service environment must include {var_name}"


# ---------------------------------------------------------------------------
# .env.example — all required variable names present
# ---------------------------------------------------------------------------

REQUIRED_ENV_EXAMPLE_VARS = [
    "DATABASE_URL",
    "JWT_SECRET",
    "JWT_EXPIRE_MINUTES",
    "COOKIE_SECURE",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
]


def test_env_example_exists():
    assert ENV_EXAMPLE.exists(), ".env.example must exist at the repository root"


@pytest.mark.parametrize("var_name", REQUIRED_ENV_EXAMPLE_VARS)
def test_env_example_contains(var_name: str):
    assert ENV_EXAMPLE.exists(), ".env.example must exist"
    content = ENV_EXAMPLE.read_text()
    # Match lines like VAR_NAME= or VAR_NAME=value (ignoring comments)
    defined_vars = [
        line.split("=")[0].strip()
        for line in content.splitlines()
        if "=" in line and not line.strip().startswith("#")
    ]
    assert var_name in defined_vars, f".env.example must document {var_name}"


# ---------------------------------------------------------------------------
# No hardcoded secrets in docker-compose.yml
# ---------------------------------------------------------------------------

# Env var keys whose values are expected to be fully interpolated (no literal secrets).
# DATABASE_URL is allowed to be a compound string containing protocol prefixes
# (e.g. postgresql+asyncpg://...) so it is excluded from the literal-secret check.
_SENSITIVE_KEYS = {
    "POSTGRES_PASSWORD",
    "POSTGRES_USER",
    "JWT_SECRET",
}

# Patterns that indicate a real literal credential rather than an interpolated ref.
# A value that consists entirely of ${...} expansions is always safe.
_BARE_LITERAL_RE = _re.compile(
    r"^(?!.*\$\{)"  # no ${...} anywhere in the value
    r".*(password|secret|changeme|admin123|letmein)",
    _re.IGNORECASE,
)


def test_compose_no_hardcoded_secret_values():
    """
    Sensitive environment variable keys must use ${VAR} interpolation, not
    literal credential strings. A value like ${POSTGRES_PASSWORD} is fine;
    a bare literal like 'mysecretpassword' is not.
    """
    compose = load_compose()
    violations: list[str] = []

    for svc_name, svc in compose.get("services", {}).items():
        env = svc.get("environment", {})
        if isinstance(env, list):
            items = [e.split("=", 1) for e in env if "=" in e]
            pairs = [(parts[0], parts[1]) for parts in items if len(parts) == 2]
        else:
            pairs = [(k, str(v)) for k, v in env.items() if v is not None]

        for key, val in pairs:
            if key not in _SENSITIVE_KEYS:
                continue
            # If the entire value is a ${...} expansion it is safe
            if _re.fullmatch(r"\$\{[^}]+\}", val.strip()):
                continue
            # Otherwise flag it — the value is not properly interpolated
            violations.append(
                f"service '{svc_name}': key '{key}' has a non-interpolated value '{val}'"
            )

    assert not violations, (
        "Hardcoded secret values found in docker-compose.yml:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# asyncpg in requirements.txt
# ---------------------------------------------------------------------------


def test_asyncpg_in_requirements():
    content = REQUIREMENTS.read_text()
    packages = [
        line.split("==")[0].split(">=")[0].split("<=")[0].strip().lower()
        for line in content.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert (
        "asyncpg" in packages
    ), "asyncpg must be listed in backend/requirements.txt for PostgreSQL async support"


# ---------------------------------------------------------------------------
# App service depends on db with health condition (or has its own healthcheck)
# ---------------------------------------------------------------------------


def test_compose_app_depends_on_db_with_health_condition():
    compose = load_compose()
    app_svc = compose["services"]["app"]
    depends_on = app_svc.get("depends_on", {})

    # depends_on can be a list ["db"] or a dict {"db": {"condition": ...}}
    if isinstance(depends_on, list):
        pytest.fail(
            "app service depends_on db, but without condition: service_healthy. "
            "Use the long-form dict with condition: service_healthy."
        )

    assert "db" in depends_on, "app service must declare depends_on: db"
    db_condition = depends_on["db"].get("condition")
    assert (
        db_condition == "service_healthy"
    ), f"app depends_on db condition must be 'service_healthy', got '{db_condition}'"
