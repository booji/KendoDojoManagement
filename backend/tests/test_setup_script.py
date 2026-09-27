"""Behavioural tests for `./setup.sh` (issue #411).

The script is the whole of first-run configuration for the quick self-host, so
these run it — against a throwaway copy of the bundle, answers piped on stdin,
and never the repository's own `.env`.

What is pinned here is the part an operator cannot check by eye: the three
secrets are generated and never regenerated on a re-run, one domain answer
reaches all three passkey-bound settings in lowercase (an `RP_ID` typo is the
whole "passkeys silently don't work" failure class), and each TLS/challenge
answer produces the Traefik config that answer implies. Prerequisite detection
is print-only and left to the operator, so only its refusal to escalate is
asserted, not its verdicts — those depend on the host running the suite.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)
SELFHOST = Path("deploy/traefik/selfhost")
PLACEHOLDERS = ("<your-db-password>", "<your-jwt-secret>", "<your-setup-token>")


def bundle(tmp_path: Path) -> Path:
    """The files `podman run <image> init | tar -x` puts in front of setup.sh."""
    home = tmp_path / "bundle"
    (home / SELFHOST / "dynamic").mkdir(parents=True)
    shutil.copy(ROOT / "setup.sh", home)
    shutil.copy(ROOT / ".env.example", home)
    shutil.copy(ROOT / SELFHOST / "traefik.yml.example", home / SELFHOST)
    for example in (ROOT / SELFHOST / "dynamic").glob("*.example"):
        shutil.copy(example, home / SELFHOST / "dynamic")
    (home / "deploy" / "sysctl-99-kendo-rootless-ports.conf").touch()
    return home


def run(home: Path, *answers: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["bash", str(home / "setup.sh")],
        input="".join(f"{a}\n" for a in answers),
        capture_output=True,
        text=True,
        cwd=home,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def env_of(home: Path, name: str = ".env") -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in (home / name).read_text().splitlines()
        if line and not line.startswith("#")
    )


def test_one_domain_answer_reaches_every_passkey_bound_setting(tmp_path):
    home = bundle(tmp_path)
    run(home, "DOJO.Example.com", "1", "1", "admin@example.com")

    env = env_of(home)
    # Lowercased: WebAuthn matches RP_ID against the browser's lowercased host.
    assert env["WEBAUTHN_RP_ID"] == "dojo.example.com"
    assert env["WEBAUTHN_ORIGIN"] == "https://dojo.example.com"
    assert env["CORS_ORIGINS"] == "https://dojo.example.com"
    assert (
        "Host(`dojo.example.com`)"
        in (home / SELFHOST / "dynamic/kendo.yml").read_text()
    )


def test_generates_the_three_secrets_and_keeps_env_unreadable_to_others(tmp_path):
    home = bundle(tmp_path)
    run(home, "dojo.example.com", "1", "1", "admin@example.com")

    env = env_of(home)
    for key in ("POSTGRES_PASSWORD", "JWT_SECRET", "SETUP_TOKEN"):
        assert re.fullmatch(r"[0-9a-f]{40,}", env[key]), f"{key} not generated"
    assert env["POSTGRES_PASSWORD"] in env["DATABASE_URL"]
    assert not any(p in (home / ".env").read_text() for p in PLACEHOLDERS)
    assert (home / ".env").stat().st_mode & 0o077 == 0


def test_rerunning_changes_the_domain_without_clobbering_the_secrets(tmp_path):
    home = bundle(tmp_path)
    run(home, "dojo.example.com", "1", "1", "admin@example.com")
    first = env_of(home)

    run(home, "shinkendo.example.org", "1", "1", "admin@example.com")
    second = env_of(home)

    for key in ("POSTGRES_PASSWORD", "JWT_SECRET", "SETUP_TOKEN"):
        assert second[key] == first[key]
    assert second["WEBAUTHN_RP_ID"] == "shinkendo.example.org"
    assert (home / ".env.bak").exists()


def test_writes_the_tag_the_bundle_was_extracted_from(tmp_path):
    home = bundle(tmp_path)
    (home / ".image-tag").write_text("ghcr.io/booji/kendodojomanagement:1.0.0-rc1\n")
    run(home, "dojo.example.com", "1", "1", "admin@example.com")

    assert env_of(home)["KENDO_IMAGE"] == "ghcr.io/booji/kendodojomanagement:1.0.0-rc1"


def test_a_checkout_keeps_the_documented_major_pin(tmp_path):
    # No .image-tag: a contributor runs this from a clone, not from a bundle.
    home = bundle(tmp_path)
    run(home, "dojo.example.com", "1", "1", "admin@example.com")

    assert env_of(home)["KENDO_IMAGE"] == "ghcr.io/booji/kendodojomanagement:1"


def acme(home: Path) -> str:
    static = (home / SELFHOST / "traefik.yml").read_text()
    return static[static.index("certificatesResolvers") : static.index("\napi:")]


def test_http_challenge_is_the_default(tmp_path):
    home = bundle(tmp_path)
    run(home, "dojo.example.com", "1", "1", "admin@example.com")

    block = acme(home)
    assert "email: admin@example.com" in block
    assert "httpChallenge:\n        entryPoint: web" in block
    assert "caServer" not in block


def test_staging_adds_the_staging_ca_server(tmp_path):
    home = bundle(tmp_path)
    run(home, "dojo.example.com", "2", "1", "admin@example.com")

    assert "acme-staging-v02.api.letsencrypt.org" in acme(home)


def test_tls_alpn_replaces_the_http_challenge(tmp_path):
    home = bundle(tmp_path)
    run(home, "dojo.example.com", "1", "2", "admin@example.com")

    block = acme(home)
    assert "tlsChallenge: {}" in block
    assert "httpChallenge" not in block


def test_dns_challenge_writes_the_provider_and_names_its_credentials(tmp_path):
    home = bundle(tmp_path)
    out = run(home, "dojo.example.com", "1", "3", "cloudflare", "admin@example.com")

    block = acme(home)
    assert "dnsChallenge:\n        provider: cloudflare" in block
    assert "resolvers:" in block
    assert "httpChallenge" not in block
    assert "CF_DNS_API_TOKEN" in out.stdout


def test_an_unknown_dns_provider_falls_back_to_naming_lego(tmp_path):
    home = bundle(tmp_path)
    out = run(home, "dojo.example.com", "1", "3", "obscuredns", "admin@example.com")

    assert "provider: obscuredns" in acme(home)
    assert "lego documents" in out.stdout


def test_a_dns_provider_slug_cannot_smuggle_yaml_into_the_static_config(tmp_path):
    home = bundle(tmp_path)
    out = run(
        home,
        "dojo.example.com",
        "1",
        "3",
        "cloudflare: x\n  evil",  # rejected, not written
        "cloudflare",
        "admin@example.com",
    )

    assert "digits, - and _ only" in out.stdout
    assert "evil" not in (home / SELFHOST / "traefik.yml").read_text()


def test_bring_your_own_cert_serves_the_default_certificate(tmp_path):
    home = bundle(tmp_path)
    out = run(home, "dojo.example.com", "3")

    router = (home / SELFHOST / "dynamic/kendo.yml").read_text()
    assert "tls: {}" in router
    assert "certResolver" not in router
    assert (home / SELFHOST / "dynamic/byo-cert.yml").exists()
    assert "deploy/certs/" in out.stdout


def test_skipping_tls_still_writes_everything_else_and_says_what_is_left(tmp_path):
    home = bundle(tmp_path)
    out = run(home, "dojo.example.com", "4")

    assert env_of(home)["WEBAUTHN_RP_ID"] == "dojo.example.com"
    assert (home / SELFHOST / "traefik.yml").exists()
    assert "certResolver" not in (home / SELFHOST / "dynamic/kendo.yml").read_text()
    assert not (home / SELFHOST / "dynamic/byo-cert.yml").exists()
    assert "no certificate is configured" in out.stdout


def test_a_domain_that_would_break_passkeys_is_rejected_before_anything_is_written(
    tmp_path,
):
    home = bundle(tmp_path)
    out = run(
        home,
        "https://dojo.example.com",  # scheme
        "localhost",  # no dot
        "dojo.example.com:8443",  # port
        "dojo.example.com",
        "1",
        "1",
        "admin@example.com",
    )

    assert out.stdout.count("Bare hostname only") == 2
    assert "cannot bind to a bare label" in out.stdout
    assert env_of(home)["WEBAUTHN_RP_ID"] == "dojo.example.com"


def test_a_hostname_with_an_empty_or_hyphen_edged_label_is_rejected(tmp_path):
    # A trailing dot is what a copy-paste out of a DNS zone file looks like, and
    # it fails every passkey ceremony as surely as a scheme does.
    home = bundle(tmp_path)
    out = run(home, "dojo.example.com.", "-dojo.example.com", "dojo.example.com", "4")

    assert out.stdout.count("Every label must be non-empty") == 2
    assert env_of(home)["WEBAUTHN_RP_ID"] == "dojo.example.com"


def test_an_unrecognised_tls_answer_re_asks_instead_of_silently_skipping_tls(tmp_path):
    # Falling through to the skip branch would leave no certificate configured
    # and print none of the warnings choice 4 prints.
    home = bundle(tmp_path)
    out = run(home, "dojo.example.com", "5", "1", "1", "admin@example.com")

    assert "Answer 1, 2, 3 or 4." in out.stdout
    assert "certResolver" in (home / SELFHOST / "dynamic/kendo.yml").read_text()
    assert "email: admin@example.com" in acme(home)


def test_a_rerun_keeps_a_contributors_own_image_pin(tmp_path):
    home = bundle(tmp_path)
    run(home, "dojo.example.com", "4")
    env = (
        (home / ".env")
        .read_text()
        .replace(
            "KENDO_IMAGE=ghcr.io/booji/kendodojomanagement:1",
            "KENDO_IMAGE=localhost/kendodojo:latest",
        )
    )
    (home / ".env").write_text(env)

    run(home, "dojo.example.com", "4")
    assert env_of(home)["KENDO_IMAGE"] == "localhost/kendodojo:latest"


def test_prerequisites_are_printed_for_the_operator_never_escalated(tmp_path):
    home = bundle(tmp_path)
    out = run(home, "dojo.example.com", "1", "1", "admin@example.com")

    assert "never escalates" in out.stdout or "all five satisfied" in out.stdout
    assert not re.search(r"^\s*sudo ", (home / "setup.sh").read_text(), re.MULTILINE)


def test_a_hand_copied_env_example_is_filled_in_not_carried_forward(tmp_path):
    # `cp .env.example .env` first, then ./setup.sh: the placeholders are not
    # secrets, and carrying them forward leaves an app that refuses to start.
    home = bundle(tmp_path)
    shutil.copy(home / ".env.example", home / ".env")
    run(home, "dojo.example.com", "1", "1", "admin@example.com")

    assert not any(p in (home / ".env").read_text() for p in PLACEHOLDERS)


# --------------------------------------------------------------- --quadlet ---
# The hardened path (#412): podman secrets, the ~/kendo/ config tree and the
# Quadlet units, instead of .env and the Compose stack. Neither podman nor a
# systemd user session exists in the test container, so both are stubbed on
# PATH — what is asserted is what the script asks them to do.

PODMAN_STUB = """#!/bin/sh
echo "$*" >> "$PODMAN_LOG"
case "$1 $2" in
  "secret inspect") [ -f "$PODMAN_STATE/$3" ] ;;
  "secret create") cat > "$PODMAN_STATE/$3" ;;
  *) exit 0 ;;
esac
"""

SYSTEMCTL_STUB = """#!/bin/sh
echo "$*" >> "$SYSTEMCTL_LOG"
"""


class Host:
    """A bundle in ~/src, a fake HOME, and stubbed podman/systemctl."""

    def __init__(self, tmp_path: Path):
        self.src = bundle(tmp_path)
        for sub in ("quadlet", "env", "bin"):
            shutil.copytree(ROOT / "deploy" / sub, self.src / "deploy" / sub)
        (self.src / "deploy/traefik/dynamic").mkdir()
        shutil.copy(ROOT / "deploy/traefik/traefik.yml", self.src / "deploy/traefik")
        for f in (ROOT / "deploy/traefik/dynamic").iterdir():
            shutil.copy(f, self.src / "deploy/traefik/dynamic")

        self.home = tmp_path / "home"
        self.home.mkdir()
        self.state = tmp_path / "secrets"
        self.state.mkdir()
        stubs = tmp_path / "bin"
        stubs.mkdir()
        for name, body in (("podman", PODMAN_STUB), ("systemctl", SYSTEMCTL_STUB)):
            (stubs / name).write_text(body)
            (stubs / name).chmod(0o755)
        self.podman_log = tmp_path / "podman.log"
        self.systemctl_log = tmp_path / "systemctl.log"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{stubs}:{os.environ['PATH']}",
            "PODMAN_STATE": str(self.state),
            "PODMAN_LOG": str(self.podman_log),
            "SYSTEMCTL_LOG": str(self.systemctl_log),
        }

    def run(self, *answers: str, expect: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["bash", str(self.src / "setup.sh"), "--quadlet"],
            input="".join(f"{a}\n" for a in answers),
            capture_output=True,
            text=True,
            cwd=self.src,
            env=self.env,
            check=False,
        )
        assert result.returncode == expect, result.stdout + result.stderr
        return result

    def secret(self, name: str) -> str:
        return (self.state / name).read_text()

    def units(self) -> Path:
        return self.home / ".config/containers/systemd"


def test_quadlet_secrets_cannot_mismatch_the_password_they_embed(tmp_path):
    # The whole reason one script owns both: DATABASE_URL and the postgres
    # password are generated together, so the trap cannot be walked into.
    host = Host(tmp_path)
    host.run("dojo.example.com", "1", "1", "admin@example.com")

    password = host.secret("kendo_postgres_password")
    assert re.fullmatch(r"[0-9a-f]{40,}", password)
    assert (
        host.secret("kendo_database_url")
        == f"postgresql+asyncpg://kendo:{password}@kendo-db:5432/kendo"
    )
    for name in ("kendo_jwt_secret", "kendo_setup_token"):
        assert re.fullmatch(r"[0-9a-f]{40,}", host.secret(name)), name
    assert not (host.state / "kendo_dns_token").exists()


def test_quadlet_lays_down_the_config_tree_the_units_expect(tmp_path):
    host = Host(tmp_path)
    host.run("dojo.example.com", "1", "1", "admin@example.com")

    kendo = host.home / "kendo"
    env = env_of(kendo, "kendo-app.env")
    assert env["WEBAUTHN_RP_ID"] == "dojo.example.com"
    assert env["WEBAUTHN_ORIGIN"] == "https://dojo.example.com"
    assert env["CORS_ORIGINS"] == "https://dojo.example.com"
    assert env["TRUST_PROXY_XFF"] == "true"

    static = (kendo / "traefik/traefik.yml").read_text()
    assert "email: admin@example.com" in static
    assert "httpChallenge:\n        entryPoint: web" in static
    assert (
        "Host(`dojo.example.com`)" in (kendo / "traefik/dynamic/kendo.yml").read_text()
    )

    assert (host.home / "backups").is_dir()
    for script in ("kendo-backup.sh", "kendo-restore.sh"):
        assert os.access(host.home / ".local/bin" / script, os.X_OK)


def test_quadlet_installs_the_units_and_reloads(tmp_path):
    host = Host(tmp_path)
    out = host.run("dojo.example.com", "1", "1", "admin@example.com")

    quadlet = ROOT / "deploy/quadlet"
    shipped = {
        p.name
        for glob in ("kendo-*.network", "kendo-*.volume", "kendo-*.container")
        for p in quadlet.glob(glob)
    }
    assert shipped, "no units found to install"
    assert shipped <= {p.name for p in host.units().iterdir() if p.is_file()}
    assert "--user daemon-reload" in host.systemctl_log.read_text()
    assert "systemctl --user start kendo-traefik" in out.stdout


def test_quadlet_wires_dns_01_credentials_as_a_drop_in(tmp_path):
    # A drop-in, not an edit to the unit: docs/deployment.md tells an operator to
    # re-copy the units on upgrade, which would revert an edit made here.
    host = Host(tmp_path)
    host.run("dojo.example.com", "1", "3", "hetzner", "admin@example.com", "tok-123")

    assert host.secret("kendo_dns_token") == "tok-123"
    dropin = (host.units() / "kendo-traefik.container.d/10-dns-01.conf").read_text()
    assert "Environment=HETZNER_API_KEY_FILE=/run/secrets/dns_token" in dropin
    assert "Secret=kendo_dns_token,type=mount,target=dns_token" in dropin
    assert "provider: hetzner" in (host.home / "kendo/traefik/traefik.yml").read_text()
    # The base unit stays provider-neutral, so HTTP-01 needs no DNS secret at all.
    assert "cf_dns_token" not in (host.units() / "kendo-traefik.container").read_text()


def test_quadlet_leaves_a_multi_variable_dns_provider_to_the_operator(tmp_path):
    # route53 wants three variables; guessing one secret for it would be wrong.
    host = Host(tmp_path)
    out = host.run("dojo.example.com", "1", "3", "route53", "admin@example.com")

    assert not (host.state / "kendo_dns_token").exists()
    assert not (host.units() / "kendo-traefik.container.d/10-dns-01.conf").exists()
    assert "AWS_ACCESS_KEY_ID" in out.stdout
    assert "10-dns-01.conf" in out.stdout


def test_quadlet_switching_away_from_dns_01_removes_the_drop_in(tmp_path):
    host = Host(tmp_path)
    host.run("dojo.example.com", "1", "3", "cloudflare", "admin@example.com", "tok")
    host.run("dojo.example.com", "1", "1", "admin@example.com")

    assert not (host.units() / "kendo-traefik.container.d/10-dns-01.conf").exists()


def test_quadlet_bring_your_own_cert_mounts_the_directory_it_asks_for(tmp_path):
    host = Host(tmp_path)
    out = host.run("dojo.example.com", "3")

    kendo = host.home / "kendo"
    assert "tls: {}" in (kendo / "traefik/dynamic/kendo.yml").read_text()
    assert (kendo / "traefik/dynamic/byo-cert.yml").exists()
    assert (kendo / "traefik/certs").is_dir()
    assert (
        "Volume=%h/kendo/traefik/certs:/etc/traefik/certs:ro,Z"
        in (host.units() / "kendo-traefik.container.d/20-byo-cert.conf").read_text()
    )
    assert str(kendo / "traefik/certs") in out.stdout


def test_quadlet_prints_the_setup_token_once_because_a_secret_is_write_only(tmp_path):
    host = Host(tmp_path)
    out = host.run("dojo.example.com", "4")

    assert host.secret("kendo_setup_token") in out.stdout
    # Second run: the secret is kept, so there is no value to show.
    again = host.run("dojo.example.com", "4")
    assert host.secret("kendo_setup_token") not in again.stdout
    assert "kept existing secret kendo_setup_token" in again.stdout


def test_quadlet_rerunning_changes_the_domain_without_rotating_the_secrets(tmp_path):
    host = Host(tmp_path)
    host.run("dojo.example.com", "4")
    before = {n.name: n.read_text() for n in host.state.iterdir()}

    host.run("shinkendo.example.org", "4")

    assert {n.name: n.read_text() for n in host.state.iterdir()} == before
    assert "shinkendo.example.org" in (host.home / "kendo/kendo-app.env").read_text()
    assert (host.home / "kendo/kendo-app.env.bak").exists()


def test_quadlet_refuses_a_half_present_database_url_pair(tmp_path):
    # The password and the URL embedding it must match, and podman will not read
    # a secret back — so completing the pair would be a guess.
    host = Host(tmp_path)
    (host.state / "kendo_postgres_password").write_text("set-by-hand")

    result = host.run("dojo.example.com", "4", expect=1)

    assert (
        "podman secret rm kendo_postgres_password kendo_database_url" in result.stderr
    )
    assert not (host.state / "kendo_database_url").exists()


def test_quadlet_pins_the_units_to_the_tag_the_bundle_came_from(tmp_path):
    host = Host(tmp_path)
    (host.src / ".image-tag").write_text(
        "ghcr.io/booji/kendodojomanagement:1.0.0-rc1\n"
    )
    host.run("dojo.example.com", "4")

    for unit in ("kendo-app.container", "kendo-migrate.container"):
        assert (
            "Image=ghcr.io/booji/kendodojomanagement:1.0.0-rc1"
            in (host.units() / unit).read_text()
        ), unit


def test_quadlet_without_podman_prints_every_prerequisite_and_writes_nothing(tmp_path):
    # Detection stays "detect and print, never escalate" (#412) even on the one
    # path that cannot continue: the operator is owed the whole list, not just
    # the prerequisite that stopped the run.
    host = Host(tmp_path)
    (tmp_path / "bin/podman").unlink()

    result = host.run("dojo.example.com", "4", expect=1)

    assert "Podman is not installed." in result.stdout
    assert "Linger is off" in result.stdout
    assert "never escalates" in result.stdout
    assert not (host.home / "kendo").exists()
    assert not any(host.state.iterdir())


def test_quadlet_re_asks_for_an_empty_dns_token(tmp_path):
    # podman refuses an empty secret, and the failure would land after the other
    # four secrets already exist — exactly the half-configured state the
    # password/URL pair is careful to avoid.
    host = Host(tmp_path)
    out = host.run(
        "dojo.example.com", "1", "3", "cloudflare", "admin@example.com", "", "tok"
    )

    assert "Empty — podman will not store an empty secret" in out.stdout
    assert host.secret("kendo_dns_token") == "tok"


def test_quadlet_never_seeds_its_secrets_from_a_compose_env(tmp_path):
    # `./setup.sh` then `./setup.sh --quadlet` in the same directory: the whole
    # point of the hardened path is that these values are not in a plaintext file.
    host = Host(tmp_path)
    run(host.src, "dojo.example.com", "4")
    compose = env_of(host.src)

    host.run("dojo.example.com", "4")

    assert host.secret("kendo_jwt_secret") != compose["JWT_SECRET"]
    assert host.secret("kendo_postgres_password") != compose["POSTGRES_PASSWORD"]
