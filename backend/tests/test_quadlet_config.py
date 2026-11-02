"""
File-based tests for the Podman Quadlet deployment units (Issue #287).

deploy/quadlet/ had zero test coverage. These are static, file-based
assertions over the *.container / *.network / *.volume unit files and
docs/deployment.md — no containers are started, no Podman is invoked.

The units were already fixed in #281; these tests are expected to pass
immediately. They exist to prevent regression (e.g. someone silently
reintroducing Internal=true, or letting the db back onto the edge network).
"""

import os
import re
from pathlib import Path

import pytest

from tests.deploy_contract import CAPABILITIES_ADDED_BACK, QUADLET_UNITS, SECRETS

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
QUADLET_DIR = ROOT / "deploy" / "quadlet"
DEPLOYMENT_DOC = ROOT / "docs" / "deployment.md"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
# Quadlet unit files are systemd-style INI, but legitimately repeat keys
# within a section (Network= twice in kendo-app.container, multiple Secret=
# lines, multiple Environment= lines). configparser.ConfigParser raises
# DuplicateOptionError on that by default, and even strict=False silently
# drops earlier values (last write wins) — which would make the "app
# straddles both networks" test vacuous since only the last Network= line
# would survive. So this is a tiny hand-rolled parser that accumulates
# repeated keys into lists instead of scalars.


def _parse_unit(text: str) -> dict[str, dict[str, list[str]]]:
    """Parse a systemd/Quadlet unit file into {section: {key: [values]}}.

    Keys keep their original case (systemd keys are CamelCase). Comment
    lines (# or ;) and blank lines are ignored. Every key's value is
    collected into a list, even if it appears once, so repeated keys are
    never silently dropped.
    """
    sections: dict[str, dict[str, list[str]]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        sections[current].setdefault(key, []).append(value)
    return sections


def load_units() -> dict[str, dict[str, dict[str, list[str]]]]:
    """Load every Quadlet unit in deploy/quadlet/, keyed by filename."""
    units: dict[str, dict[str, dict[str, list[str]]]] = {}
    for path in QUADLET_DIR.iterdir():
        if path.is_file():
            units[path.name] = _parse_unit(path.read_text())
    return units


def _networks(unit: dict[str, dict[str, list[str]]]) -> list[str]:
    return unit.get("Container", {}).get("Network", [])


def _all_container_files() -> list[str]:
    return sorted(p for p in load_units() if p.endswith(".container"))


# ---------------------------------------------------------------------------
# 1 & 2 & 3 — network segmentation
# ---------------------------------------------------------------------------


def test_db_is_only_on_the_backend_network():
    units = load_units()
    networks = _networks(units["kendo-db.container"])
    assert networks == ["kendo-backend.network"], (
        f"kendo-db must be on the backend network only, never the edge. Got: {networks}"
    )


def test_app_straddles_both_networks():
    units = load_units()
    networks = sorted(_networks(units["kendo-app.container"]))
    assert networks == ["kendo-backend.network", "kendo-edge.network"], (
        "kendo-app must be on both networks: edge to serve traffic, backend "
        f"to reach the db. Got: {networks}"
    )


def test_traefik_is_edge_only():
    units = load_units()
    networks = _networks(units["kendo-traefik.container"])
    assert networks == ["kendo-edge.network"], (
        f"kendo-traefik must be on the edge network only. Got: {networks}"
    )


# ---------------------------------------------------------------------------
# 4 & 5 — published ports
# ---------------------------------------------------------------------------


def test_only_traefik_publishes_ports():
    units = load_units()
    publishers = [
        name
        for name in _all_container_files()
        if units[name].get("Container", {}).get("PublishPort")
    ]
    assert publishers == ["kendo-traefik.container"], (
        f"kendo-traefik must be the only unit declaring PublishPort=. Got: {publishers}"
    )
    ports = units["kendo-traefik.container"]["Container"]["PublishPort"]
    assert sorted(ports) == [
        "443:443",
        "80:80",
    ], f"kendo-traefik must publish 80:80 and 443:443. Got: {ports}"


def test_db_declares_no_published_port():
    units = load_units()
    ports = units["kendo-db.container"].get("Container", {}).get("PublishPort")
    assert not ports, f"kendo-db must not declare PublishPort=. Got: {ports}"


# ---------------------------------------------------------------------------
# 6 & 7 — network unit hardening (#281 regression guard)
# ---------------------------------------------------------------------------


def test_no_network_unit_sets_internal_true():
    units = load_units()
    offenders = []
    for name, unit in units.items():
        if not name.endswith(".network"):
            continue
        values = [v.lower() for v in unit.get("Network", {}).get("Internal", [])]
        if "true" in values:
            offenders.append(name)
    assert not offenders, (
        "No .network unit may set Internal=true — Podman disables DNS on "
        f"internal networks (#281). Offenders: {offenders}"
    )


def test_every_network_unit_sets_isolate_true():
    units = load_units()
    for name, unit in units.items():
        if not name.endswith(".network"):
            continue
        options = unit.get("Network", {}).get("Options", [])
        assert any(opt.strip() == "isolate=true" for opt in options), (
            f"{name} must set Options=isolate=true. Got: {options}"
        )


# ---------------------------------------------------------------------------
# 8 & 9 — cross-references resolve to real unit files
# ---------------------------------------------------------------------------


def test_every_network_reference_resolves_to_a_network_file():
    units = load_units()
    network_files = {name for name in units if name.endswith(".network")}
    for cname in _all_container_files():
        for ref in _networks(units[cname]):
            assert ref in network_files, (
                f"{cname} references Network={ref}, but no such .network "
                f"file exists in deploy/quadlet/. Known: {sorted(network_files)}"
            )


def test_every_volume_reference_resolves_to_a_volume_file():
    units = load_units()
    volume_files = {name for name in units if name.endswith(".volume")}
    for cname in _all_container_files():
        volume_lines = units[cname].get("Container", {}).get("Volume", [])
        for line in volume_lines:
            # Syntax: Volume=<source>:<dest>[:options] — only the source
            # segment is a candidate unit reference, and only if it ends in
            # .volume; a bind mount path or anonymous volume is not.
            source = line.split(":", 1)[0]
            if not source.endswith(".volume"):
                continue
            assert source in volume_files, (
                f"{cname} references Volume={source}, but no such .volume "
                f"file exists in deploy/quadlet/. Known: {sorted(volume_files)}"
            )


# ---------------------------------------------------------------------------
# 10 — secrets arrive via Secret=, never inline
# ---------------------------------------------------------------------------

_LITERAL_SECRET_KEY_RE = re.compile(r"(SECRET|PASSWORD)$")


def test_secrets_never_appear_as_inline_literals():
    units = load_units()
    violations = []
    for name in _all_container_files():
        env_lines = units[name].get("Container", {}).get("Environment", [])
        for line in env_lines:
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # POSTGRES_PASSWORD_FILE=/run/secrets/... is the correct
            # indirection form and must pass.
            if key.endswith("_FILE"):
                continue

            # A key literally named *_SECRET or *_PASSWORD with a real value
            # (not a _FILE indirection) is a leaked credential.
            if _LITERAL_SECRET_KEY_RE.search(key) and value:
                violations.append(f"{name}: {key}={value}")

            # A connection-string style value with an embedded password,
            # e.g. postgresql://user:password@host — flag any scheme://
            # value containing '@' with credentials before it.
            if re.search(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^/@]+:[^/@]+@", value):
                violations.append(f"{name}: {key}={value}")

    assert not violations, (
        "Secrets must arrive via Secret=, never as inline literal values. "
        f"Violations: {violations}"
    )


# ---------------------------------------------------------------------------
# 11 — app waits for db
# ---------------------------------------------------------------------------


def test_app_requires_and_waits_for_db():
    units = load_units()
    unit_section = units["kendo-app.container"].get("Unit", {})
    assert "kendo-db.service" in unit_section.get("Requires", []), (
        "kendo-app.container must declare Requires=kendo-db.service"
    )
    assert "kendo-db.service" in unit_section.get("After", []), (
        "kendo-app.container must declare After=kendo-db.service"
    )


# ---------------------------------------------------------------------------
# 12 — docs/units consistency (the #281 bug exactly)
# ---------------------------------------------------------------------------


def test_docs_database_url_host_matches_db_container_name():
    units = load_units()
    db_container_name = units["kendo-db.container"]["Container"]["ContainerName"][0]

    doc_text = DEPLOYMENT_DOC.read_text()
    match = re.search(r"postgresql\+asyncpg://[^@]+@([^:/\s']+)", doc_text)
    assert match, (
        "Could not find a DATABASE_URL example in docs/deployment.md to check "
        "the db host against"
    )
    docs_host = match.group(1)

    assert docs_host == db_container_name, (
        "The DB host in the DATABASE_URL example in docs/deployment.md "
        f"('{docs_host}') must match ContainerName= in "
        f"deploy/quadlet/kendo-db.container ('{db_container_name}')"
    )


# ---------------------------------------------------------------------------
# 13 — the env file the Quadlet unit reads (#385)
# ---------------------------------------------------------------------------
# kendo-app.container passes exactly one EnvironmentFile plus its secrets, so
# anything absent from deploy/env/kendo-app.env.example is absent from the
# app's environment on a Quadlet host. APP_ENV was, which left
# validate_startup_config() on its permissive development path: a placeholder
# RP ID, an http:// origin, or an RP ID that does not match the origin host
# all booted cleanly and failed later in the browser. docker-compose.yml
# defaults APP_ENV to production and so was never affected — this is the file
# that has to carry it for the Quadlet path.


def _app_env_example() -> dict[str, str]:
    """Parse deploy/env/kendo-app.env.example into {KEY: value}."""
    path = ROOT / "deploy" / "env" / "kendo-app.env.example"
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_app_env_file_is_the_only_environment_source():
    """The premise of the test below: if a second EnvironmentFile or an
    inline Environment= ever appears on kendo-app.container, checking the
    example file alone stops being sufficient."""
    app = load_units()["kendo-app.container"]["Container"]
    assert app.get("EnvironmentFile") == ["%h/kendo/kendo-app.env"]
    # The one exception: each mounted secret's <NAME>_FILE path (#462), which
    # pairs with its Secret= line and is no setting of the operator's.
    inline = [
        e
        for e in app.get("Environment", [])
        if not re.fullmatch(r"[A-Z_]+_FILE=/run/secrets/[a-z_]+", e)
    ]
    assert not inline, (
        "kendo-app.container now sets Environment= inline; the env-file "
        f"checks below no longer see the app's whole environment: {inline}"
    )


def test_app_env_example_sets_production_app_env():
    assert _app_env_example().get("APP_ENV") == "production", (
        "deploy/env/kendo-app.env.example must set APP_ENV=production, or a "
        "Quadlet deployment skips every production WebAuthn check in "
        "validate_startup_config()"
    )


def test_uploads_volume_is_chowned_to_the_container_user():
    """The image runs as a non-root USER (#385). Podman only derives a volume's
    ownership from the image directory when the volume is empty, so a volume
    created by an earlier root-running image stays root-owned and uploads fail
    with EACCES after the upgrade. `:U` chowns it to the container user on every
    start, which keeps the upgrade path free of a manual `podman unshare chown`.
    """
    mounts = load_units()["kendo-app.container"]["Container"]["Volume"]
    uploads = [m for m in mounts if "kendo-app-uploads" in m]
    assert uploads, mounts
    assert uploads[0].endswith(":U"), uploads


# ---------------------------------------------------------------------------
# 14 — migrations are their own oneshot unit (#391)
# ---------------------------------------------------------------------------
# entrypoint.sh no longer runs `alembic upgrade head`: kendo-migrate owns it.
# A failed migration then fails as its own unit instead of as an app container
# that exits, and the app never binds :8000 against a half-migrated schema.


def test_app_requires_and_waits_for_the_migration_unit():
    unit_section = load_units()["kendo-app.container"].get("Unit", {})
    for key in ("Requires", "After"):
        assert "kendo-migrate.service" in unit_section.get(key, []), (
            f"kendo-app.container must declare {key}=kendo-migrate.service — "
            "otherwise the app can start against an unmigrated schema (#391)"
        )


def test_migrate_unit_is_a_oneshot_that_waits_for_db():
    migrate = load_units()["kendo-migrate.container"]
    assert migrate.get("Service", {}).get("Type") == ["oneshot"], (
        "kendo-migrate.container must set Type=oneshot in [Service]; a default "
        "Type=notify unit never reaches 'active' and blocks kendo-app forever"
    )
    assert "kendo-db.service" in migrate.get("Unit", {}).get("After", [])


# ---------------------------------------------------------------------------
# Recovery-attempt IPs are cleared daily, not only on a recovery attempt (#467)
# ---------------------------------------------------------------------------


def test_ip_retention_unit_is_a_oneshot_running_the_clear():
    unit = load_units()["kendo-ip-retention.container"]
    container = unit["Container"]
    assert container.get("Entrypoint") == ["python"], container
    assert container.get("Exec") == ["-m app.cli clear-expired-ip-addresses"]
    assert _networks(unit) == ["kendo-backend.network"]
    assert unit.get("Service", {}).get("Type") == ["oneshot"]
    # RemainAfterExit=yes would leave it active, and a timer cannot start an
    # active unit again: it would run once and never again.
    assert "RemainAfterExit" not in unit.get("Service", {}), unit["Service"]
    # Requires=, as kendo-app has: After= alone orders, it does not pull
    # kendo-migrate in, so the clear could run against an unmigrated schema.
    assert {"kendo-db.service", "kendo-migrate.service"} <= set(
        unit["Unit"].get("Requires", [])
    )
    assert {"kendo-db.service", "kendo-migrate.service"} <= set(
        unit["Unit"].get("After", [])
    )


def test_ip_retention_timer_triggers_the_unit_daily():
    """A plain systemd timer: Quadlet generates no timers, so it installs to
    ~/.config/systemd/user/ and activates the service named after it."""
    timer = _parse_unit(
        (ROOT / "deploy" / "systemd" / "kendo-ip-retention.timer").read_text()
    )
    assert timer["Timer"].get("OnCalendar") == ["daily"], timer
    # A host that was off at midnight runs it on the next boot.
    assert timer["Timer"].get("Persistent") == ["true"], timer
    assert timer["Install"].get("WantedBy") == ["timers.target"], timer


def test_every_unit_dependency_resolves_to_a_container_file():
    """Requires=/After= naming a *.service must have a matching .container.

    Network= and Volume= references are checked above; without this, adding
    Requires=kendo-migrate.service while forgetting to `git add` the unit
    file leaves every operator with an app systemd refuses to start
    ("Unit kendo-migrate.service not found").
    """
    units = load_units()
    known = {name.removesuffix(".container") + ".service" for name in units}
    for cname in _all_container_files():
        unit_section = units[cname].get("Unit", {})
        refs = unit_section.get("Requires", []) + unit_section.get("After", [])
        for ref in refs:
            if not ref.endswith(".service"):
                continue
            assert ref in known, (
                f"{cname} references {ref}, but deploy/quadlet/ has no unit "
                f"file for it. Known: {sorted(known)}"
            )


# ---------------------------------------------------------------------------
# The superuser login reaches the migration step only (#453, ADR-0007)
# ---------------------------------------------------------------------------


def test_superuser_login_is_attached_to_the_migrate_unit_only():
    units = load_units()

    def secrets(name: str) -> str:
        return " ".join(units[name].get("Container", {}).get("Secret", []))

    assert "kendo_migration_database_url," in secrets("kendo-migrate.container")
    # The app user's login: bootstrap reads its name and password from it.
    assert "kendo_database_url," in secrets("kendo-migrate.container")
    app = secrets("kendo-app.container")
    assert "kendo_migration_database_url" not in app, app
    assert "kendo_postgres_password" not in app, app


# ---------------------------------------------------------------------------
# Secrets reach the app as files, never as environment (#462)
# ---------------------------------------------------------------------------
# A mounted secret is a file under /run/secrets, and app/config.py reads its
# path from <NAME>_FILE.


def _secret_options(container: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    """{secret name: {option: value}} for each Secret= line."""
    out = {}
    for line in container.get("Secret", []):
        name, *opts = line.split(",")
        out[name] = dict(opt.split("=", 1) for opt in opts)
    return out


# kendo-ip-retention has no Compose service, so it is added here by unit.
UNIT_SECRETS = {QUADLET_UNITS[s]: names for s, names in SECRETS.items()} | {
    "kendo-ip-retention.container": ["DATABASE_URL"]
}


@pytest.mark.parametrize("unit", sorted(UNIT_SECRETS))
def test_app_secrets_are_mounted_files_named_in_their_file_variable(unit: str):
    container = load_units()[unit]["Container"]
    env = dict(e.split("=", 1) for e in container.get("Environment", []))
    secrets = _secret_options(container)
    assert sorted(secrets) == sorted(f"kendo_{v.lower()}" for v in UNIT_SECRETS[unit])

    for var in UNIT_SECRETS[unit]:
        secret = f"kendo_{var.lower()}"
        opts = secrets[secret]
        assert opts.get("type") == "mount", f"{unit}: {secret} {opts}"
        # Readable by the image's unprivileged user (uid 1001) and nobody else.
        assert (opts.get("uid"), opts.get("gid"), opts.get("mode")) == (
            "1001",
            "1001",
            "0400",
        ), f"{unit}: {secret} {opts}"
        assert env.get(f"{var}_FILE") == f"/run/secrets/{opts['target']}", env
        assert var not in env, f"{unit} still passes {var} as environment"


# ---------------------------------------------------------------------------
# Container hardening: assume the app is breached (#458). The same settings on
# the Compose services are checked in test_docker_config.py.
# ---------------------------------------------------------------------------


HARDENED_UNITS = {
    QUADLET_UNITS[s]: caps for s, caps in CAPABILITIES_ADDED_BACK.items()
} | {"kendo-ip-retention.container": []}


def _hardened_container(unit: str) -> dict[str, list[str]]:
    return load_units()[unit]["Container"]


@pytest.mark.parametrize("service", sorted(HARDENED_UNITS))
def test_hardened_units_run_with_a_read_only_root(service: str):
    """An attacker with code execution cannot drop tools into the image
    filesystem. /tmp stays writable (Starlette spools uploads there); the
    uploads and ACME volumes are mounts and stay writable too."""
    container = _hardened_container(service)
    assert container.get("ReadOnly") == ["true"], container
    assert "/tmp" in container.get("Tmpfs", []), container


@pytest.mark.parametrize("service", sorted(HARDENED_UNITS))
def test_hardened_units_drop_every_capability_and_privilege_escalation(
    service: str,
):
    container = _hardened_container(service)
    assert container.get("DropCapability") == ["ALL"], container
    assert container.get("AddCapability", []) == HARDENED_UNITS[service]
    assert container.get("NoNewPrivileges") == ["true"], container


@pytest.mark.parametrize("service", sorted(HARDENED_UNITS))
def test_hardened_units_cap_pids_and_memory(service: str):
    """A breached container cannot fork-bomb or exhaust the host. PodmanArgs
    rather than the PidsLimit=/Memory= keys: Memory= is not in Podman 4.9
    (Ubuntu 24.04), and an unknown key stops Quadlet generating the unit. A
    later `PodmanArgs=--memory=…` in a drop-in wins, which is how hosts tune it.
    """
    args = " ".join(_hardened_container(service).get("PodmanArgs", []))
    assert re.search(r"--pids-limit=\d+\b", args), args
    assert re.search(r"--memory=\d+[kmg]\b", args), args


# systemd has no inline comments: in `Persistent=true  # catch up`, everything
# after `=` is the value, so the boolean fails to parse and systemd ignores
# the setting with only a log warning. kendo-backup.timer shipped that way.
UNIT_FILES = sorted(
    p
    for d in (QUADLET_DIR, ROOT / "deploy" / "systemd")
    for p in d.iterdir()
    if p.is_file()
)


@pytest.mark.parametrize("path", UNIT_FILES, ids=lambda p: p.name)
def test_unit_settings_carry_no_inline_comment(path: Path):
    offenders = [
        line
        for line in path.read_text().splitlines()
        if "=" in line
        and not line.lstrip().startswith(("#", ";"))
        and re.search(r"\s[#;]", line.split("=", 1)[1])
    ]
    assert not offenders, (
        f"{path.name}: move the comment onto its own line: {offenders}"
    )
