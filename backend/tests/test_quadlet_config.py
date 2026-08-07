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
        "kendo-db must be on the backend network only, never the edge. "
        f"Got: {networks}"
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
    assert networks == [
        "kendo-edge.network"
    ], f"kendo-traefik must be on the edge network only. Got: {networks}"


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
        "kendo-traefik must be the only unit declaring PublishPort=. "
        f"Got: {publishers}"
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
        assert any(
            opt.strip() == "isolate=true" for opt in options
        ), f"{name} must set Options=isolate=true. Got: {options}"


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
    assert "kendo-db.service" in unit_section.get(
        "Requires", []
    ), "kendo-app.container must declare Requires=kendo-db.service"
    assert "kendo-db.service" in unit_section.get(
        "After", []
    ), "kendo-app.container must declare After=kendo-db.service"


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
