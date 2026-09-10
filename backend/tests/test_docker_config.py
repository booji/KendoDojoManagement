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
DEV_COMPOSE_FILE = ROOT / "docker-compose.dev.yml"
ENV_EXAMPLE = ROOT / ".env.example"
REQUIREMENTS = ROOT / "backend" / "requirements.txt"


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
    assert (
        "backend" in networks
    ), "docker-compose.dev.yml must define a 'backend' network"


def test_dev_compose_frontend_cannot_reach_the_database():
    """The frontend runs arbitrary npm dependencies — keep it off the db network."""
    frontend_networks = _networks_of(load_dev_compose()["services"]["frontend"])
    assert "backend" not in frontend_networks, (
        "frontend must NOT be on the backend network: it runs arbitrary npm "
        "dependencies with node_modules mounted and must not be able to reach "
        f"PostgreSQL. Got: {frontend_networks}"
    )
    assert frontend_networks == [
        "edge"
    ], f"frontend must be on the edge network only. Got: {frontend_networks}"


def test_dev_compose_db_is_only_on_the_backend_network():
    db_networks = _networks_of(load_dev_compose()["services"]["db"])
    assert db_networks == [
        "backend"
    ], f"dev db must be on the backend network only. Got: {db_networks}"


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


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


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
    assert any(
        "/etc/traefik/dynamic" in v for v in volumes
    ), f"the dev proxy must mount the dynamic config directory. Got: {volumes}"
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
    assert _env_values(ENV_DEV).get(key) == expected


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
    assert app["environment"]["TRUST_PROXY_XFF"] == "${TRUST_PROXY_XFF:-true}"


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
    assert _re.search(
        r"chown[^\n]*/app/uploads", stage
    ), "the prod stage must chown /app/uploads to the runtime user"


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
