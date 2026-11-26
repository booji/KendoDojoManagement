"""
File-based tests for Production Docker Compose configuration (Issue #5).
No live Docker required — these inspect files on disk.
"""

import os
import re as _re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from tests.deploy_contract import (
    CAPABILITIES_ADDED_BACK,
    GENERATED_ENV_FILES,
    PUBLISHED_IMAGE,
    RELEASE_PIN,
    SECRETS,
    container_env,
    names_a_registry,
    read_env_file,
)

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
DEV_COMPOSE_FILE = ROOT / "docker-compose.dev.yml"
ENV_EXAMPLE = ROOT / ".env.example"
PYPROJECT = ROOT / "backend" / "pyproject.toml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_compose() -> dict:
    with COMPOSE_FILE.open() as f:
        return yaml.safe_load(f)


def load_dev_compose() -> dict:
    with DEV_COMPOSE_FILE.open() as f:
        return yaml.safe_load(f)


def _networks_of(service: dict) -> list[str]:
    """Service networks as a list, tolerating the mapping form.

    Compose accepts both `networks: [edge]` and `networks: {edge: {...}}`.
    """
    networks = service.get("networks", [])
    if isinstance(networks, dict):
        return list(networks.keys())
    return list(networks)


# ---------------------------------------------------------------------------
# docker-compose.yml — services
# ---------------------------------------------------------------------------


def test_compose_has_app_service():
    compose = load_compose()
    assert "app" in compose.get("services", {}), (
        "docker-compose.yml must define an 'app' service"
    )


def test_compose_has_db_service():
    compose = load_compose()
    assert "db" in compose.get("services", {}), (
        "docker-compose.yml must define a 'db' service"
    )


# ---------------------------------------------------------------------------
# docker-compose.yml — named volume
# ---------------------------------------------------------------------------


def test_compose_has_named_postgres_volume():
    compose = load_compose()
    top_level_volumes = compose.get("volumes", {})
    assert top_level_volumes, (
        "docker-compose.yml must declare at least one named volume"
    )

    db_service = compose["services"]["db"]
    db_volumes = db_service.get("volumes", [])
    volume_names = list(top_level_volumes.keys())

    mounted = any(
        any(vol_name in str(v) for vol_name in volume_names) for v in db_volumes
    )
    assert mounted, (
        "The db service must mount a top-level named volume for postgres data"
    )


# ---------------------------------------------------------------------------
# docker-compose.yml — app service env vars
# ---------------------------------------------------------------------------

REQUIRED_APP_ENV_VARS = [
    # The secrets themselves are mounted files (#462): the environment only
    # names where they are.
    "DATABASE_URL_FILE",
    "JWT_SECRET_FILE",
    "SETUP_TOKEN_FILE",
    "JWT_EXPIRE_MINUTES",
    "COOKIE_SECURE",
    "SESSION_MAX_MINUTES",
]


@pytest.mark.parametrize("var_name", REQUIRED_APP_ENV_VARS)
def test_compose_app_service_env_includes(var_name: str):
    app_env = _container_env(load_compose()["services"]["app"])
    assert var_name in app_env, f"app service environment must include {var_name}"


@pytest.mark.parametrize("service", ["app", "migrate"])
def test_compose_app_image_reads_the_app_settings_quadlet_reads(service: str):
    """#603: the one example both deployments write their app settings from.
    Every key in it reaches the container, so a new one needs no compose
    change. The upload paths are pinned over it in the compose file."""
    spec = load_compose()["services"][service]
    assert spec.get("env_file") == "kendo-app.env", spec
    example = read_env_file(ROOT / GENERATED_ENV_FILES["kendo-app.env"])
    env = _container_env(spec)
    assert example.keys() <= env.keys(), example.keys() - env.keys()


# What the compose file interpolates, and the secrets setup.sh turns into
# mounted files. Anything else in .env would be an app setting no container
# reads (#603): those live in kendo-app.env.
COMPOSE_ENV_KEYS = {
    "KENDO_IMAGE",
    "TZ",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "MIGRATION_DATABASE_URL",
    "DATABASE_URL",
    "JWT_SECRET",
    "SETUP_TOKEN",
}


def test_env_example_holds_only_what_compose_interpolates_and_the_secrets():
    assert read_env_file(ENV_EXAMPLE).keys() == COMPOSE_ENV_KEYS


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


def test_compose_db_timezone_defaults_to_the_apps():
    """An .env without TZ must not leave the db on another zone than the app,
    whose TZ comes from the shared example (Europe/London, as in Quadlet)."""
    db_tz = str(load_compose()["services"]["db"]["environment"]["TZ"])
    default = _re.fullmatch(r"\$\{TZ:-([^}]*)\}", db_tz)
    assert default, db_tz
    app_tz = read_env_file(ROOT / GENERATED_ENV_FILES["kendo-app.env"])["TZ"]
    assert default.group(1) == app_tz == read_env_file(ENV_EXAMPLE)["TZ"]


# ---------------------------------------------------------------------------
# .env.example — all required variable names present
# ---------------------------------------------------------------------------

REQUIRED_ENV_EXAMPLE_VARS = [
    "DATABASE_URL",
    "JWT_SECRET",
    "SETUP_TOKEN",
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
    "SETUP_TOKEN",
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
# asyncpg in the runtime dependencies
# ---------------------------------------------------------------------------


def test_asyncpg_in_requirements():
    deps = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    packages = [_re.split(r"[=<>~!\[;]", d)[0].strip().lower() for d in deps]
    assert "asyncpg" in packages, (
        "asyncpg must be a [project] dependency in backend/pyproject.toml "
        "for PostgreSQL async support"
    )


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
    assert db_condition == "service_healthy", (
        f"app depends_on db condition must be 'service_healthy', got '{db_condition}'"
    )


# ---------------------------------------------------------------------------
# Network segmentation (Issue #278)
#
# Both stacks mirror the Quadlet deployment in deploy/quadlet: an `edge` network
# carrying the published ports, and a `backend` network that is the only path to
# PostgreSQL. These assertions exist because the isolation was otherwise
# verified only by hand — nothing stopped a later edit from silently putting the
# database back on the edge, or restoring host networking.
# ---------------------------------------------------------------------------


def test_compose_defines_edge_and_backend_networks():
    networks = load_compose().get("networks") or {}
    assert "edge" in networks, "docker-compose.yml must define an 'edge' network"
    assert "backend" in networks, "docker-compose.yml must define a 'backend' network"


def test_compose_db_is_only_on_the_backend_network():
    db_networks = _networks_of(load_compose()["services"]["db"])
    assert db_networks == ["backend"], (
        "db must be on the backend network only, so nothing on the edge can "
        f"reach PostgreSQL. Got: {db_networks}"
    )


def test_compose_app_straddles_both_networks():
    app_networks = sorted(_networks_of(load_compose()["services"]["app"]))
    assert app_networks == ["backend", "edge"], (
        "app must be on both networks: edge to serve traffic, backend to reach "
        f"the db. Got: {app_networks}"
    )


def test_dev_compose_defines_edge_and_backend_networks():
    networks = load_dev_compose().get("networks") or {}
    assert "edge" in networks, "docker-compose.dev.yml must define an 'edge' network"
    assert "backend" in networks, (
        "docker-compose.dev.yml must define a 'backend' network"
    )


def test_dev_compose_frontend_cannot_reach_the_database():
    """The frontend runs arbitrary npm dependencies — keep it off the db network."""
    frontend_networks = _networks_of(load_dev_compose()["services"]["frontend"])
    assert "backend" not in frontend_networks, (
        "frontend must NOT be on the backend network: it runs arbitrary npm "
        "dependencies with node_modules mounted and must not be able to reach "
        f"PostgreSQL. Got: {frontend_networks}"
    )
    assert frontend_networks == ["edge"], (
        f"frontend must be on the edge network only. Got: {frontend_networks}"
    )


def test_dev_compose_db_is_only_on_the_backend_network():
    db_networks = _networks_of(load_dev_compose()["services"]["db"])
    assert db_networks == ["backend"], (
        f"dev db must be on the backend network only. Got: {db_networks}"
    )


@pytest.mark.parametrize(
    "compose_name", ["docker-compose.yml", "docker-compose.dev.yml"]
)
def test_networks_are_isolated_from_each_other(compose_name: str):
    """Podman bridge networks are mutually routable by IP without this option.

    Without `isolate`, a container on the edge network cannot *resolve* `db` but
    can still open a socket to its address, which makes the segmentation
    cosmetic. Verified on podman 5.6.0.
    """
    compose = (
        load_compose() if compose_name == "docker-compose.yml" else load_dev_compose()
    )
    networks = compose.get("networks") or {}
    # Without this the loop below iterates nothing and the test passes vacuously.
    assert networks, f"{compose_name} must define networks"
    for name, network in networks.items():
        opts = (network or {}).get("driver_opts") or {}
        assert str(opts.get("isolate", "")).lower() == "true", (
            f"{compose_name}: network '{name}' must set driver_opts.isolate=true, "
            "otherwise containers on different networks reach each other by IP"
        )


@pytest.mark.parametrize(
    "compose_name", ["docker-compose.yml", "docker-compose.dev.yml"]
)
def test_no_service_uses_host_networking(compose_name: str):
    """Host-networked containers join no Compose network, so nothing is segmented.

    It also made the dev database bind host port 5432 directly (#275).
    """
    compose = (
        load_compose() if compose_name == "docker-compose.yml" else load_dev_compose()
    )
    offenders = [
        name
        for name, svc in compose.get("services", {}).items()
        if (svc or {}).get("network_mode") == "host"
    ]
    assert not offenders, (
        f"{compose_name}: services must not use network_mode: host "
        f"(found: {offenders}) — it bypasses network segmentation entirely"
    )


def test_dev_compose_db_port_is_bound_to_loopback():
    """Dev credentials are weak and committed, so the port must not reach the LAN."""
    ports = load_dev_compose()["services"]["db"].get("ports", [])
    assert ports, "dev db must publish a port for host-side alembic/psql"
    for mapping in ports:
        assert str(mapping).startswith("127.0.0.1:"), (
            "dev db port must be bound to 127.0.0.1, not every interface. "
            f"Got: {mapping}"
        )


# ---------------------------------------------------------------------------
# Traefik in the dev stack and the quick self-host (Issue #374)
#
# The proxy exists so that Secure cookies, the WebAuthn origin/RP ID and the
# X-Forwarded-For path are exercised in development instead of for the first
# time in production. These assertions pin the contract the runtime reads —
# services, ports, mounts, routing rules and the security-relevant env values.
# ---------------------------------------------------------------------------

DEV_TRAEFIK_STATIC = ROOT / "deploy" / "traefik" / "dev" / "traefik.yml"
DEV_TRAEFIK_DYNAMIC = ROOT / "deploy" / "traefik" / "dev" / "dynamic" / "kendo.yml"
# The live copies are gitignored (they carry the operator's domain and ACME
# email); the tracked .example files next to them are what this repository ships.
SELFHOST_TRAEFIK_STATIC = (
    ROOT / "deploy" / "traefik" / "selfhost" / "traefik.yml.example"
)
SELFHOST_TRAEFIK_DYNAMIC = (
    ROOT / "deploy" / "traefik" / "selfhost" / "dynamic" / "kendo.yml.example"
)
TEST_COMPOSE_FILE = ROOT / "docker-compose.test.yml"
ENV_DEV = ROOT / ".env.dev"

DEV_HOST = "dojo.localhost"
DEV_ORIGIN = "https://dojo.localhost:8443"


def test_dev_compose_has_a_proxy_on_the_edge_network_only():
    proxy = load_dev_compose()["services"].get("proxy")
    assert proxy, "docker-compose.dev.yml must define a 'proxy' service (Traefik)"
    assert _networks_of(proxy) == ["edge"], (
        "the dev proxy must be on the edge network only — it must never be able "
        f"to reach PostgreSQL. Got: {_networks_of(proxy)}"
    )


def test_dev_proxy_publishes_unprivileged_ports():
    """8443/8080 rather than 443/80, so rootless needs no sysctl change."""
    ports = [str(p) for p in load_dev_compose()["services"]["proxy"].get("ports", [])]
    assert any(p.startswith("8443:") for p in ports), f"expected 8443 in {ports}"
    assert any(p.startswith("8080:") for p in ports), f"expected 8080 in {ports}"
    for mapping in ports:
        host_port = int(mapping.split(":")[0])
        assert host_port >= 1024, f"dev proxy must bind unprivileged ports: {mapping}"


def test_dev_proxy_mounts_its_config_and_no_container_runtime_socket():
    volumes = [str(v) for v in load_dev_compose()["services"]["proxy"]["volumes"]]
    assert any("/etc/traefik/dynamic" in v for v in volumes), (
        f"the dev proxy must mount the dynamic config directory. Got: {volumes}"
    )
    for v in volumes:
        assert "docker.sock" not in v and "podman.sock" not in v, (
            "the dev proxy must not mount the container runtime socket — the "
            f"hardened deployment deliberately does not either. Got: {v}"
        )


def test_dev_proxy_declares_no_depends_on():
    """A depends_on here reorders podman-compose's startup, and the backend then
    attaches to the edge network first. Its resolv.conf lists the edge resolver
    first, a `db` lookup there is NXDOMAIN, and glibc does not fall through to
    the next nameserver — so the backend cannot reach PostgreSQL at all.
    Observed on podman 5.6.0 / podman-compose 1.5.0.
    """
    proxy = load_dev_compose()["services"]["proxy"]
    assert "depends_on" not in proxy, (
        "the dev proxy must not declare depends_on — it breaks service-name DNS "
        "for the backend, and Traefik retries its upstreams anyway"
    )


def test_dev_proxy_routes_the_api_and_the_spa_to_the_right_services():
    config = yaml.safe_load(DEV_TRAEFIK_DYNAMIC.read_text())
    routers = config["http"]["routers"]
    services = config["http"]["services"]

    def backend_url(router: dict) -> str:
        service = services[router["service"]]
        return service["loadBalancer"]["servers"][0]["url"]

    api_routers = [r for r in routers.values() if "/api" in r["rule"]]
    assert api_routers, f"no router matches /api in {DEV_TRAEFIK_DYNAMIC}"
    assert "backend:8000" in backend_url(api_routers[0])

    spa_routers = [r for r in routers.values() if "/api" not in r["rule"]]
    assert spa_routers, f"no catch-all SPA router in {DEV_TRAEFIK_DYNAMIC}"
    assert "frontend:5173" in backend_url(spa_routers[0])

    for router in routers.values():
        assert DEV_HOST in router["rule"], (
            f"every dev router must be bound to {DEV_HOST}, so the origin the "
            f"browser uses is the one passkeys are registered against: {router['rule']}"
        )


def test_dev_traefik_uses_the_file_provider_and_not_the_socket_provider():
    config = yaml.safe_load(DEV_TRAEFIK_STATIC.read_text())
    assert "file" in config["providers"], "the dev proxy must use the file provider"
    assert "docker" not in config["providers"], (
        "the label provider needs the runtime socket mounted, which the hardened "
        "deployment deliberately avoids"
    )


DEV_ENV_EXPECTATIONS = {
    # A cookie-attribute mistake must surface locally, not at cutover.
    "COOKIE_SECURE": "true",
    # Rate limiting and lockout take the client IP from X-Forwarded-For in
    # production; dev must exercise the same path.
    "TRUST_PROXY_XFF": "true",
    "WEBAUTHN_RP_ID": DEV_HOST,
    "WEBAUTHN_ORIGIN": DEV_ORIGIN,
    "CORS_ORIGINS": DEV_ORIGIN,
    # Still development: the production-only WEBAUTHN_* default checks must not
    # fire against the dev values.
    "APP_ENV": "development",
}


@pytest.mark.parametrize("key,expected", sorted(DEV_ENV_EXPECTATIONS.items()))
def test_env_dev_matches_the_proxied_origin(key: str, expected: str):
    assert read_env_file(ENV_DEV).get(key) == expected


def test_dev_backend_and_frontend_keep_their_direct_ports():
    """The escape hatch: a missing certificate must never block development."""
    services = load_dev_compose()["services"]
    backend_ports = [str(p) for p in services["backend"].get("ports", [])]
    frontend_ports = [str(p) for p in services["frontend"].get("ports", [])]
    assert "8000:8000" in backend_ports, backend_ports
    assert "5173:5173" in frontend_ports, frontend_ports


def test_selfhost_app_publishes_no_port_and_trusts_the_forwarded_header():
    """One unit: XFF is only safe because there is no unproxied route left."""
    app = load_compose()["services"]["app"]
    assert not app.get("ports"), (
        "the quick self-host's app must not publish a port once the proxy fronts "
        f"it — an unproxied route makes TRUST_PROXY_XFF spoofable. Got: {app.get('ports')}"
    )
    assert _container_env(app)["TRUST_PROXY_XFF"] == "true"


def test_selfhost_has_a_proxy_on_the_edge_network_only():
    proxy = load_compose()["services"].get("proxy")
    assert proxy, "docker-compose.yml must define a 'proxy' service (Traefik)"
    assert _networks_of(proxy) == ["edge"], _networks_of(proxy)
    for v in [str(v) for v in proxy["volumes"]]:
        assert "docker.sock" not in v and "podman.sock" not in v, v


def test_selfhost_traefik_issues_certificates_over_the_http_challenge():
    """The quick path needs an inbound port, not a DNS-provider credential."""
    acme = yaml.safe_load(SELFHOST_TRAEFIK_STATIC.read_text())["certificatesResolvers"][
        "letsencrypt"
    ]["acme"]
    assert "httpChallenge" in acme, acme
    assert "dnsChallenge" not in acme, "the DNS challenge belongs to deploy/quadlet"


def test_selfhost_router_targets_the_app_service():
    config = yaml.safe_load(SELFHOST_TRAEFIK_DYNAMIC.read_text())
    urls = [
        s["loadBalancer"]["servers"][0]["url"]
        for s in config["http"]["services"].values()
    ]
    assert any("app:8000" in url for url in urls), urls


def test_test_stack_defines_no_proxy():
    """An ~11 minute e2e suite does not grow a hop for fidelity it does not test."""
    with TEST_COMPOSE_FILE.open() as f:
        services = yaml.safe_load(f).get("services", {})
    assert "proxy" not in services and "traefik" not in services, list(services)


def test_dev_frontend_proxy_origin_can_be_emptied_for_the_escape_hatch():
    """Vite's `server.ws` is server-wide, so one dev server cannot serve HMR to
    both origins. Pinning DEV_PROXY_ORIGIN in the compose file left the :5173
    escape hatch with an HMR client dialling the proxy it exists to bypass
    (#382); an interpolated default lets `DEV_PROXY_ORIGIN=` swap which origin
    gets working HMR.
    """
    env = load_dev_compose()["services"]["frontend"]["environment"]
    assert env["DEV_PROXY_ORIGIN"] == f"${{DEV_PROXY_ORIGIN-{DEV_ORIGIN}}}", env


# ---------------------------------------------------------------------------
# Production image hardening and edge health checking (#385)
# ---------------------------------------------------------------------------

DOCKERFILE = ROOT / "Dockerfile"
QUADLET_TRAEFIK_DYNAMIC = ROOT / "deploy" / "traefik" / "dynamic" / "kendo.yml"


def _prod_stage() -> str:
    """The final `FROM ... AS prod` stage of the Dockerfile, as text."""
    text = DOCKERFILE.read_text()
    marker = _re.search(r"^FROM .* AS prod$", text, _re.MULTILINE)
    assert marker, "Dockerfile has no `FROM ... AS prod` stage"
    return text[marker.start() :]


def test_prod_image_runs_as_a_non_root_user():
    """Rootless Podman maps container-root to the unprivileged host user, but
    inside the container it is still root: writable image code, writable
    site-packages. A USER line costs nothing and bounds that (#385)."""
    user = _re.findall(r"^USER (.+)$", _prod_stage(), _re.MULTILINE)
    assert user, "the prod stage must declare a USER"
    assert user[-1].strip() not in ("root", "0"), user


def test_prod_image_owns_the_upload_directories():
    """`/app/uploads` does not otherwise exist in the image — main.py mkdirs it
    at import, i.e. after the volume is mounted. Podman's copy-up takes a fresh
    named volume's ownership from the image directory, so the directory must
    exist and belong to the runtime user or the first upload hits EACCES."""
    stage = _prod_stage()
    assert "/app/uploads" in stage, stage
    assert _re.search(r"chown[^\n]*/app/uploads", stage), (
        "the prod stage must chown /app/uploads to the runtime user"
    )


@pytest.mark.parametrize(
    "path",
    [QUADLET_TRAEFIK_DYNAMIC, SELFHOST_TRAEFIK_DYNAMIC],
    ids=["quadlet", "selfhost"],
)
def test_prod_traefik_health_checks_the_app(path: Path):
    """entrypoint.sh runs `alembic upgrade head` before uvicorn binds :8000, so
    every restart has a window where nothing listens. Without a health check
    Traefik reports that as 502 Bad Gateway — a health check makes it the
    truthful 503 Service Unavailable (#385)."""
    services = yaml.safe_load(path.read_text())["http"]["services"]
    health = services["kendo"]["loadBalancer"].get("healthCheck")
    assert health, f"{path.name}: the kendo service needs a loadBalancer healthCheck"
    assert health["path"] == "/health", health


# ---------------------------------------------------------------------------
# docker-compose.yml — the stack comes back after a crash, OOM or reboot (#582)
# ---------------------------------------------------------------------------


def test_compose_long_running_services_come_back_on_their_own():
    """Every service declares a restart policy: `always` unless it is a
    one-shot job that says `"no"`. `always`, not `unless-stopped`: an older
    Podman's podman-restart.service starts only `always` containers at boot."""
    services = load_compose()["services"]
    policies = {name: svc.get("restart") for name, svc in services.items()}
    long_running = {name for name, policy in policies.items() if policy != "no"}
    assert long_running >= {"app", "proxy", "db"}, policies
    for name in long_running:
        assert policies[name] == "always", (
            f"{name} must set `restart: always`, or the dojo stays offline "
            "after an OOM kill or a reboot (#582)"
        )


# ---------------------------------------------------------------------------
# docker-compose.yml — migrations run before the app, not inside it (#391)
# ---------------------------------------------------------------------------


def test_compose_app_waits_for_migrate_to_complete():
    compose = load_compose()
    app_deps = compose["services"]["app"].get("depends_on", {})
    assert app_deps.get("migrate", {}).get("condition") == (
        "service_completed_successfully"
    ), "app must start only after the migrate service exits 0 (#391)"
    migrate_deps = compose["services"]["migrate"].get("depends_on", {})
    assert migrate_deps.get("db", {}).get("condition") == "service_healthy"


def test_app_container_does_not_run_migrations():
    """One owner for `alembic upgrade head`: the migrate service/unit.

    Both halves matter. entrypoint.sh is the obvious one; app/main.py's
    lifespan is the one that made #391's first attempt a no-op — the
    entrypoint had stopped migrating while `_init_db()` still called
    prepare_database() on every start, so a failed migration still took the
    app container down with it.
    """
    entrypoint = (ROOT / "entrypoint.sh").read_text()
    assert "app.db.bootstrap" not in entrypoint, entrypoint

    main = (ROOT / "backend" / "app" / "main.py").read_text()
    assert "prepare_database" not in main, (
        "app/main.py must not run migrations: the app is ordered after the "
        "migrate unit, which owns `alembic upgrade head` (#391)"
    )


# ---------------------------------------------------------------------------
# Deployments run the published image, and it carries its own bundle (#410,
# ADR-0004)
# ---------------------------------------------------------------------------

RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
QUADLET_UNITS = [
    ROOT / "deploy" / "quadlet" / "kendo-app.container",
    ROOT / "deploy" / "quadlet" / "kendo-migrate.container",
    ROOT / "deploy" / "quadlet" / "kendo-ip-retention.container",
]


BUNDLE_FILES = [
    ROOT / "setup.sh",
    ROOT / "entrypoint.sh",
    COMPOSE_FILE,
    ENV_EXAMPLE,
    *sorted(p for p in (ROOT / "deploy").rglob("*") if p.is_file()),
]


@pytest.mark.parametrize("path", BUNDLE_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_shipped_files_name_only_the_current_pin(path: Path):
    """No stale tag in what an operator runs or reads: before 1.0 a `:1` pin
    names an image that does not exist yet, and `:0` one that is never pushed."""
    pins = _re.findall(
        rf"{_re.escape(PUBLISHED_IMAGE)}:[0-9]+(?:\.[0-9]+)*", path.read_text()
    )
    assert set(pins) <= {RELEASE_PIN}, pins


@pytest.mark.parametrize("service", ["app", "migrate"])
def test_compose_runs_the_published_image_and_never_builds(service: str):
    """An operator pulls; they do not build. `build:` alongside `image:` would
    quietly rebuild from a context they no longer have."""
    spec = load_compose()["services"][service]
    assert "build" not in spec, spec
    assert spec["image"] == f"${{KENDO_IMAGE:-{RELEASE_PIN}}}", spec["image"]


@pytest.mark.parametrize(
    "image, qualified",
    [
        ("postgres:16-alpine", False),
        ("library/postgres:16-alpine", False),
        ("${KENDO_IMAGE:-kendodojo:latest}", False),
        ("docker.io/library/postgres:16-alpine", True),
        ("localhost/kendodojo:latest", True),
        (f"${{KENDO_IMAGE:-{RELEASE_PIN}}}", True),
    ],
)
def test_names_a_registry_rejects_short_names(image: str, qualified: bool):
    assert names_a_registry(image) is qualified


def test_every_compose_image_names_its_registry():
    """A short name resolves through the host's search registries, and on
    RHEL-family hosts that is registry.access.redhat.com first (#634)."""
    images = {name: spec["image"] for name, spec in load_compose()["services"].items()}
    assert all(names_a_registry(i) for i in images.values()), images


def test_env_example_pins_the_same_image_as_the_compose_default():
    assert f"\nKENDO_IMAGE={RELEASE_PIN}\n" in ENV_EXAMPLE.read_text()


@pytest.mark.parametrize("unit", QUADLET_UNITS, ids=lambda p: p.name)
def test_quadlet_units_run_the_published_image(unit: Path):
    """Every app-image unit, always the same tag: the migration chain and the code that
    runs against it have to come from one artefact."""
    text = unit.read_text()
    assert f"\nImage={RELEASE_PIN}\n" in text, text
    assert "Image=localhost/kendodojo" not in text, text


def test_entrypoint_hands_over_the_bundle_before_starting_uvicorn():
    """`init` is the only argument entrypoint.sh interprets: a tar of /bundle
    to stdout, so an operator gets the compose file and config without a clone.
    It must short-circuit — reaching uvicorn would start the app instead."""
    entrypoint = (ROOT / "entrypoint.sh").read_text()
    assert 'if [ "$1" = "init" ]' in entrypoint, entrypoint
    assert entrypoint.index("tar -C /bundle") < entrypoint.index("exec uvicorn")


def test_bundle_ships_the_deployment_files_without_the_dev_only_ones():
    """Everything under /bundle is published to operators at that tag, and
    deploy/certs and deploy/traefik/dev are per-machine dev material.

    They must be excluded from the build context, not deleted after the COPY:
    a layer keeps what a later `rm` removes, so a dev machine's TLS private
    keys would stay extractable from the pushed image.
    """
    stage = _prod_stage()
    assert "COPY setup.sh docker-compose.yml .env.example /bundle/" in stage, stage
    assert "COPY deploy/ /bundle/deploy/" in stage, stage
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    assert "deploy/certs" in ignored, ignored
    assert "deploy/traefik/dev" in ignored, ignored


def test_bundle_carries_the_tag_it_was_extracted_from():
    """setup.sh writes the image pin into .env rather than prompting for it, so
    the bundle has to know which tag it came out of (#411, ADR-0004). The build
    arg is unset for a contributor's `make build`, and setup.sh then falls back
    to .env.example's own default rather than pinning localhost/kendodojo.
    """
    stage = _prod_stage()
    assert 'ARG KENDO_IMAGE_REF=""' in stage, stage
    assert "/bundle/.image-tag" in stage, stage

    release = RELEASE_WORKFLOW.read_text()
    assert "KENDO_IMAGE_REF=${{ steps.pin.outputs.ref }}" in release, release


def test_release_image_reports_its_exact_version():
    """Admin Settings shows the Version the image was built from (#556): the
    exact tag, `0.1.5`, never the pin `0.1`. Any other build reports `dev`."""
    stage = _prod_stage()
    # Empty, so `dev` lives only in the router: an unset or empty
    # KENDO_VERSION reports `dev` there.
    assert "\nARG KENDO_VERSION=\n" in stage, stage
    assert "ENV KENDO_VERSION=$KENDO_VERSION" in stage, stage

    [build] = [s for s in _release_steps() if s.get("id") == "build"]
    args = build["with"]["build-args"].splitlines()
    assert "KENDO_VERSION=${{ steps.meta.outputs.version }}" in args, args


def _release_steps() -> list[dict]:
    jobs = yaml.safe_load(RELEASE_WORKFLOW.read_text())["jobs"]
    return [step for job in jobs.values() for step in job["steps"]]


def _pin_for(version: str, tmp_path: Path) -> str:
    """Run release.yml's own pin step for the version metadata-action emits."""
    [step] = [s for s in _release_steps() if s.get("id") == "pin"]
    script = step["run"].replace("${{ steps.meta.outputs.version }}", version)
    out = tmp_path / "github_output"
    out.touch()
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        env={**os.environ, "GITHUB_OUTPUT": str(out)},
        check=True,
    )
    return dict(line.split("=", 1) for line in out.read_text().splitlines())["ref"]


def _shipped_pin_check(ref: str) -> subprocess.CompletedProcess:
    """Run release.yml's own check that the shipped files name REF."""
    [step] = [s for s in _release_steps() if s.get("id") == "pin-check"]
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        cwd=ROOT,
        env={**os.environ, "REF": ref},
        capture_output=True,
        text=True,
    )


def test_release_publishes_when_the_shipped_files_name_its_pin():
    result = _shipped_pin_check(RELEASE_PIN)
    assert result.returncode == 0, result.stdout + result.stderr


def test_release_checks_the_pin_before_pushing_and_never_for_a_prerelease():
    """An rc is pushed under its exact tag, which no shipped file names."""
    steps = _release_steps()
    ids = [s.get("id") for s in steps]
    assert ids.index("pin") < ids.index("pin-check") < ids.index("build"), ids
    check = steps[ids.index("pin-check")]
    assert check["if"] == "${{ !contains(github.ref_name, '-') }}", check


def test_release_refuses_a_pin_the_shipped_files_do_not_name():
    """A new Release line that missed a file must not publish: an operator
    would extract a bundle, or read a page, that pulls the old line. The
    failure names every such file."""
    result = _shipped_pin_check(f"{PUBLISHED_IMAGE}:99")
    assert result.returncode != 0, result.stdout
    pages = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]
    stale = {
        path.relative_to(ROOT).as_posix()
        for path in [*BUNDLE_FILES, *pages]
        if RELEASE_PIN in path.read_text(errors="ignore")
    }
    assert stale
    missed = {path for path in stale if path not in result.stdout}
    assert not missed, result.stdout


@pytest.mark.parametrize(
    ("version", "pin"),
    [
        # Before 1.0 the minor stands in for the major (ADR-0009): a :0 pin
        # would hand every 0.x Breaking change to `pull && up -d`.
        ("0.1.0", "0.1"),
        ("0.3.1", "0.3"),
        # From 1.0 the major, with no edit to the workflow (ADR-0004).
        ("1.2.0", "1"),
        ("2.0.5", "2"),
        # A prerelease rehearses one exact image, never a moving tag.
        ("0.1.0-rc1", "0.1.0-rc1"),
        ("1.0.0-rc1", "1.0.0-rc1"),
    ],
)
def test_release_bakes_the_pin_its_series_documents(version, pin, tmp_path):
    assert _pin_for(version, tmp_path) == f"{PUBLISHED_IMAGE}:{pin}"


def test_release_never_pushes_a_moving_zero_tag():
    """metadata-action emits `0` for {{major}} on a 0.x version unless the
    entry is disabled (its README's "Major version zero"), and `:0` would carry
    every 0.x Breaking change. 0.Y and 0.Y.Z still publish."""
    [meta] = [s for s in _release_steps() if s.get("id") == "meta"]
    tags = meta["with"]["tags"].splitlines()
    assert "type=semver,pattern={{version}}" in tags, tags
    assert "type=semver,pattern={{major}}.{{minor}}" in tags, tags
    [major] = [t for t in tags if "pattern={{major}}," in t or t.endswith("{{major}}")]
    assert major == (
        "type=semver,pattern={{major}},"
        "enable=${{ !startsWith(github.ref, 'refs/tags/v0.') }}"
    ), major


# ---------------------------------------------------------------------------
# The app connects as the least-privilege user, never the superuser (#453,
# ADR-0007)
# ---------------------------------------------------------------------------


def _container_env(service: dict) -> dict[str, str]:
    return container_env(service, ROOT, GENERATED_ENV_FILES)


@pytest.mark.parametrize(
    "load, service",
    [(load_compose, "app"), (load_dev_compose, "backend")],
    ids=["compose-app", "dev-backend"],
)
def test_compose_app_never_sees_the_superuser_login(load, service: str):
    spec = load()["services"][service]
    env = _container_env(spec)
    # Prod names a mounted file (<NAME>_FILE, #462), dev passes the value.
    names = {k.removesuffix("_FILE") for k in env}
    for superuser_var in (
        "MIGRATION_DATABASE_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ):
        assert superuser_var not in names, env
    assert "migration_database_url" not in spec.get("secrets", []), spec
    assert "POSTGRES_PASSWORD" not in env.get("DATABASE_URL", ""), env


def test_dev_backend_still_gets_every_app_setting_from_env_dev():
    """Dropping env_file (#483) must not drop the app's own settings with it:
    everything in .env.dev except the superuser and host-tooling values."""
    env = _container_env(load_dev_compose()["services"]["backend"])
    wanted = {
        key
        for key in read_env_file(ENV_DEV)
        if not key.startswith("POSTGRES_") and key != "MIGRATION_DATABASE_URL"
    }
    assert wanted <= env.keys(), wanted - env.keys()


@pytest.mark.parametrize("load", [load_compose, load_dev_compose], ids=["prod", "dev"])
def test_compose_migrate_gets_both_logins(load):
    env = _container_env(load()["services"]["migrate"])
    names = {k.removesuffix("_FILE") for k in env}
    assert {"DATABASE_URL", "MIGRATION_DATABASE_URL"} <= names, env


# ---------------------------------------------------------------------------
# Prod secrets are mounted files, not environment (#462)
# ---------------------------------------------------------------------------
# Compose mounts a file-backed secret at /run/secrets/<name>; setup.sh writes
# the files under ./secrets.


@pytest.mark.parametrize("service", sorted(SECRETS))
def test_compose_secrets_are_mounted_files(service: str):
    compose = load_compose()
    spec = compose["services"][service]
    env = _container_env(spec)
    for var in SECRETS[service]:
        name = var.lower()
        assert var not in env, f"{service} still passes {var} as environment"
        assert env.get(f"{var}_FILE") == f"/run/secrets/{name}", env
        assert name in spec.get("secrets", []), spec
        assert compose["secrets"][name] == {"file": f"./secrets/{name}"}


def test_dev_backend_waits_for_migrate():
    """The dev backend refuses to start as the superuser, so its app user has
    to exist first — and only the migration step creates it."""
    deps = load_dev_compose()["services"]["backend"].get("depends_on", {})
    assert deps.get("migrate", {}).get("condition") == "service_completed_successfully"


@pytest.mark.parametrize("env_file", [".env.example", ".env.dev", ".env.test"])
def test_env_files_split_the_app_and_migration_logins(env_file: str):
    from sqlalchemy.engine.url import make_url

    values = read_env_file(ROOT / env_file)
    assert make_url(values["DATABASE_URL"]).username == "kendo_app"
    migration = make_url(values["MIGRATION_DATABASE_URL"])
    assert migration.username == values["POSTGRES_USER"]
    assert migration.password == values["POSTGRES_PASSWORD"]


# ---------------------------------------------------------------------------
# Container hardening: assume the app is breached (#458). The same settings on
# the Quadlet units are checked in test_quadlet_config.py.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("service", sorted(CAPABILITIES_ADDED_BACK))
def test_compose_services_run_with_a_read_only_root(service: str):
    spec = load_compose()["services"][service]
    assert spec.get("read_only") is True, spec
    assert "/tmp" in spec.get("tmpfs", []), spec


@pytest.mark.parametrize("service", sorted(CAPABILITIES_ADDED_BACK))
def test_compose_services_drop_every_capability_and_privilege_escalation(
    service: str,
):
    spec = load_compose()["services"][service]
    assert spec.get("cap_drop") == ["ALL"], spec
    assert spec.get("cap_add", []) == CAPABILITIES_ADDED_BACK[service]
    assert "no-new-privileges:true" in spec.get("security_opt", []), spec


@pytest.mark.parametrize("service", sorted(CAPABILITIES_ADDED_BACK))
def test_compose_services_cap_pids_and_memory(service: str):
    spec = load_compose()["services"][service]
    assert isinstance(spec.get("pids_limit"), int), spec
    assert _re.fullmatch(r"\d+[kmg]", str(spec.get("mem_limit"))), spec
