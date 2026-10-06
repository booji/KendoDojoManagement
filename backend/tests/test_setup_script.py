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

from tests.backup_support import decrypt, keypair, no_file_holds

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
    assert env["MIGRATION_DATABASE_URL"] == (
        f"postgresql+asyncpg://kendo:{env['POSTGRES_PASSWORD']}@db:5432/kendo"
    )
    # The app's own login (ADR-0007), with a password of its own.
    app_password = re.fullmatch(
        r"postgresql\+asyncpg://kendo_app:([0-9a-f]{40,})@db:5432/kendo",
        env["DATABASE_URL"],
    )
    assert app_password, env["DATABASE_URL"]
    assert app_password.group(1) != env["POSTGRES_PASSWORD"]
    assert not any(p in (home / ".env").read_text() for p in PLACEHOLDERS)
    assert (home / ".env").stat().st_mode & 0o077 == 0


def test_rerunning_changes_the_domain_without_clobbering_the_secrets(tmp_path):
    home = bundle(tmp_path)
    run(home, "dojo.example.com", "1", "1", "admin@example.com")
    first = env_of(home)

    run(home, "shinkendo.example.org", "1", "1", "admin@example.com")
    second = env_of(home)

    for key in ("POSTGRES_PASSWORD", "DATABASE_URL", "JWT_SECRET", "SETUP_TOKEN"):
        assert second[key] == first[key]
    assert second["WEBAUTHN_RP_ID"] == "shinkendo.example.org"
    assert (home / ".env.bak").exists()


def test_rerunning_moves_a_pre_453_env_onto_the_app_user(tmp_path):
    # The documented upgrade (#453): an .env whose DATABASE_URL is still the
    # superuser's gets an app-user login, and the database password is kept.
    home = bundle(tmp_path)
    run(home, "dojo.example.com", "1", "1", "admin@example.com")
    first = env_of(home)
    old = (
        (home / ".env")
        .read_text()
        .replace(first["DATABASE_URL"], first["MIGRATION_DATABASE_URL"])
    )
    (home / ".env").write_text(old)

    run(home, "dojo.example.com", "1", "1", "admin@example.com")
    second = env_of(home)

    assert second["POSTGRES_PASSWORD"] == first["POSTGRES_PASSWORD"]
    assert second["MIGRATION_DATABASE_URL"] == first["MIGRATION_DATABASE_URL"]
    assert second["DATABASE_URL"].startswith("postgresql+asyncpg://kendo_app:")


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
    # The whole reason one script owns both: MIGRATION_DATABASE_URL and the postgres
    # password are generated together, so the trap cannot be walked into.
    host = Host(tmp_path)
    host.run("dojo.example.com", "1", "1", "admin@example.com")

    password = host.secret("kendo_postgres_password")
    assert re.fullmatch(r"[0-9a-f]{40,}", password)
    assert (
        host.secret("kendo_migration_database_url")
        == f"postgresql+asyncpg://kendo:{password}@kendo-db:5432/kendo"
    )
    # The app's own login (ADR-0007): kendo-migrate sets this user's password
    # from it, so it pairs with nothing.
    assert re.fullmatch(
        r"postgresql\+asyncpg://kendo_app:[0-9a-f]{40,}@kendo-db:5432/kendo",
        host.secret("kendo_database_url"),
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
    # A drop-in, not an edit to the unit: docs/install/upgrading.md tells an
    # operator to re-copy the units on upgrade, which would revert an edit made here.
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


def test_quadlet_rerun_keeps_an_operator_written_multi_variable_drop_in(tmp_path):
    # Re-running to change the domain must not strip Traefik of the route53
    # credentials the operator wired up by hand (#423).
    host = Host(tmp_path)
    host.run("dojo.example.com", "1", "3", "route53", "admin@example.com")
    dropin = host.units() / "kendo-traefik.container.d/10-dns-01.conf"
    own = "[Container]\nSecret=kendo_aws_key,type=env,target=AWS_ACCESS_KEY_ID\n"
    dropin.write_text(own)

    out = host.run("new.example.com", "1", "3", "route53", "admin@example.com")

    assert dropin.read_text() == own
    assert "kept your" in out.stdout


def test_quadlet_moving_to_a_multi_variable_provider_drops_its_own_drop_in(tmp_path):
    # A drop-in setup.sh wrote for hetzner would hand route53 the wrong secret.
    host = Host(tmp_path)
    host.run("dojo.example.com", "1", "3", "hetzner", "admin@example.com", "tok")
    host.run("dojo.example.com", "1", "3", "route53", "admin@example.com")

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
        "podman secret rm kendo_postgres_password kendo_migration_database_url"
        in result.stderr
    )
    assert not (host.state / "kendo_migration_database_url").exists()


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


# ------------------------------------------------------------------ check ---
# `./setup.sh check` (#413): advisory, re-runnable, exit non-zero on any FAIL.
# Every host probe it makes is stubbed on PATH as a healthy host, so each test
# breaks exactly one thing and the verdicts do not depend on the machine
# running the suite.

DOMAIN = "dojo.shinbukan.org"
ANSWERS = (DOMAIN, "1", "1", "admin@shinbukan.org")

GREEN_HOST = {
    "podman": 'case "$1 $2" in "secret inspect") [ -f "$PODMAN_STATE/$3" ] ;; esac',
    "sysctl": "echo 80",
    "firewall-cmd": "echo ssh http https",
    "id": '[ "$1" = -un ] && echo kendo; exit 0',
    "loginctl": "echo Linger=yes",
    "getent": 'echo "203.0.113.7     STREAM $2"',
    "hostname": "echo 192.168.1.5 203.0.113.7",
    "ss": "exit 0",
}


def host_env(tmp_path: Path, **stubs: str | None) -> dict[str, str]:
    """A healthy host, with any probe overridden by keyword (`ss=...`), or
    left unstubbed with None."""
    bindir = tmp_path / "check-bin"
    bindir.mkdir(exist_ok=True)
    overrides = {name.replace("_", "-"): body for name, body in stubs.items()}
    for name, body in {**GREEN_HOST, **overrides}.items():
        if body is None:
            continue
        path = bindir / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)
    state = tmp_path / "secrets"
    state.mkdir(exist_ok=True)
    return {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "PODMAN_STATE": str(state),
    }


def check(home: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(home / "setup.sh"), "check", *args],
        capture_output=True,
        text=True,
        cwd=home,
        env=env,
        check=False,
    )


def test_check_passes_what_setup_just_wrote_on_a_healthy_host(tmp_path):
    home = bundle(tmp_path)
    run(home, *ANSWERS)

    out = check(home, host_env(tmp_path))

    assert out.returncode == 0, out.stdout + out.stderr
    assert "FAIL" not in out.stdout
    assert "podman-compose up -d" in out.stdout


def test_check_before_setup_says_to_run_setup_first(tmp_path):
    home = bundle(tmp_path)

    out = check(home, host_env(tmp_path))

    assert out.returncode == 1
    assert "FAIL  .env is missing — run ./setup.sh first" in out.stdout


def test_check_names_every_placeholder_a_hand_copied_config_still_has(tmp_path):
    home = bundle(tmp_path)
    shutil.copy(home / ".env.example", home / ".env")
    shutil.copy(
        home / SELFHOST / "traefik.yml.example", home / SELFHOST / "traefik.yml"
    )
    shutil.copy(
        home / SELFHOST / "dynamic/kendo.yml.example",
        home / SELFHOST / "dynamic/kendo.yml",
    )

    out = check(home, host_env(tmp_path))

    assert out.returncode == 1
    for placeholder in (
        "<your-domain.com>",
        "<your-jwt-secret>",
        "dojo.example.com",
        "you@example.com",
    ):
        assert placeholder in out.stdout, placeholder


def test_check_fails_while_tls_is_still_skipped(tmp_path):
    # The skip option deliberately leaves the stack unfinished (#411); Traefik
    # would serve its self-signed default and the browser would say so.
    home = bundle(tmp_path)
    run(home, DOMAIN, "4")

    out = check(home, host_env(tmp_path))

    assert out.returncode == 1
    assert "No certificate is configured" in out.stdout


def test_check_follows_a_byo_certificate_to_its_files_and_mount(tmp_path):
    home = bundle(tmp_path)
    shutil.copy(ROOT / "docker-compose.yml", home)
    run(home, DOMAIN, "3")
    env = host_env(tmp_path)

    assert "deploy/certs/cert.pem" in check(home, env).stdout

    (home / "deploy/certs").mkdir()
    for pem in ("cert.pem", "key.pem"):
        (home / "deploy/certs" / pem).touch()
    unmounted = check(home, env)
    assert unmounted.returncode == 1
    assert "docker-compose.yml does not mount deploy/certs" in unmounted.stdout

    compose = (home / "docker-compose.yml").read_text()
    (home / "docker-compose.yml").write_text(
        compose.replace(
            "      - traefik_acme:/acme\n",
            "      - traefik_acme:/acme\n      - ./deploy/certs:/etc/traefik/certs:ro\n",
        )
    )
    assert check(home, env).returncode == 0


def test_check_warns_that_a_staging_certificate_is_untrusted(tmp_path):
    home = bundle(tmp_path)
    run(home, DOMAIN, "2", "1", "admin@shinbukan.org")

    out = check(home, host_env(tmp_path))

    assert out.returncode == 0
    assert "warn  Let's Encrypt staging" in out.stdout


def test_check_catches_a_domain_changed_in_only_one_place(tmp_path):
    # A hand edit of .env after a domain change, the router left behind.
    home = bundle(tmp_path)
    run(home, *ANSWERS)
    env = (home / ".env").read_text().replace(DOMAIN, "kendo.shinbukan.org")
    (home / ".env").write_text(env)

    out = check(home, host_env(tmp_path))

    assert out.returncode == 1
    assert f"routes {DOMAIN}" in out.stdout
    assert "WEBAUTHN_RP_ID is kendo.shinbukan.org" in out.stdout


def test_check_catches_a_blank_secret_and_a_password_the_url_no_longer_embeds(
    tmp_path,
):
    # Rotating POSTGRES_PASSWORD by hand without MIGRATION_DATABASE_URL: the
    # migrate service then fails to log in.
    home = bundle(tmp_path)
    run(home, *ANSWERS)
    before = env_of(home)
    env = (
        (home / ".env")
        .read_text()
        .replace(
            f"POSTGRES_PASSWORD={before['POSTGRES_PASSWORD']}",
            "POSTGRES_PASSWORD=rotated-by-hand",
        )
        .replace(f"JWT_SECRET={before['JWT_SECRET']}", "JWT_SECRET=")
    )
    (home / ".env").write_text(env)

    out = check(home, host_env(tmp_path))

    assert out.returncode == 1
    assert "JWT_SECRET is blank" in out.stdout
    assert "MIGRATION_DATABASE_URL does not embed POSTGRES_PASSWORD" in out.stdout


def test_check_quadlet_passes_its_own_setup_and_names_a_missing_secret(tmp_path):
    host = Host(tmp_path)
    host.run(*ANSWERS)
    env = host_env(tmp_path)

    green = check(host.src, env, "--quadlet")
    assert green.returncode == 0, green.stdout
    assert "systemctl --user start kendo-traefik" in green.stdout

    (host.state / "kendo_jwt_secret").unlink()
    out = check(host.src, env, "--quadlet")
    assert out.returncode == 1
    assert "podman secret missing: kendo_jwt_secret" in out.stdout


def test_check_fails_a_domain_that_does_not_resolve(tmp_path):
    home = bundle(tmp_path)
    run(home, *ANSWERS)

    out = check(home, host_env(tmp_path, getent="exit 2"))

    assert out.returncode == 1
    assert f"{DOMAIN} does not resolve" in out.stdout


def test_check_only_warns_when_dns_points_off_this_host(tmp_path):
    # Behind NAT the record holds the router's public address, which is never an
    # address on this box — right for a home server, wrong everywhere else, and
    # nothing here can tell which.
    home = bundle(tmp_path)
    run(home, *ANSWERS)

    out = check(home, host_env(tmp_path, hostname="echo 192.168.1.5"))

    assert out.returncode == 0, out.stdout
    assert f"warn  {DOMAIN} resolves to 203.0.113.7" in out.stdout
    assert "NAT" in out.stdout


def listening_on_80(process: str) -> str:
    return (
        'case "$*" in *":80"*) echo "LISTEN 0 511 0.0.0.0:80 0.0.0.0:* '
        f'users:((\\"{process}\\",pid=812,fd=6))" ;; esac'
    )


def test_check_names_whatever_already_holds_port_80(tmp_path):
    home = bundle(tmp_path)
    run(home, *ANSWERS)

    out = check(home, host_env(tmp_path, ss=listening_on_80("nginx")))

    assert out.returncode == 1
    assert "FAIL  :80 is taken by nginx" in out.stdout
    assert "ok    :443 is free" in out.stdout


def test_check_accepts_the_ports_held_by_the_running_stack(tmp_path):
    # Re-run after an upgrade, stack up: rootless Podman's forwarder owns 80/443.
    home = bundle(tmp_path)
    run(home, *ANSWERS)

    out = check(home, host_env(tmp_path, ss=listening_on_80("pasta.avx2")))

    assert out.returncode == 0, out.stdout
    assert ":80 is held by rootless Podman" in out.stdout


def test_check_fails_an_outstanding_prerequisite_with_the_command_that_fixes_it(
    tmp_path,
):
    home = bundle(tmp_path)
    run(home, *ANSWERS)

    out = check(home, host_env(tmp_path, loginctl="echo Linger=no"))

    assert out.returncode == 1
    assert "FAIL  Linger is off for kendo" in out.stdout
    assert "sudo loginctl enable-linger kendo" in out.stdout


def test_check_only_warns_about_a_firewall_it_cannot_see(tmp_path):
    # No firewalld or ufw: a cloud security group or the router may well be
    # doing the job, so this cannot be a FAIL that no operator can clear.
    home = bundle(tmp_path)
    run(home, *ANSWERS)

    out = check(home, host_env(tmp_path, firewall_cmd=None))

    assert out.returncode == 0, out.stdout
    assert "warn  No firewalld or ufw found" in out.stdout


def test_check_quadlet_wants_the_secrets_a_hand_written_drop_in_names(tmp_path):
    # route53 needs several variables, so the drop-in is the operator's own,
    # with secret names of their choosing (and a pre-#412 host keeps its
    # kendo_cf_dns_token): the names come from the units, not from a list here.
    host = Host(tmp_path)
    host.run(DOMAIN, "1", "3", "route53", "admin@shinbukan.org")
    dropin = host.units() / "kendo-traefik.container.d/10-dns-01.conf"
    dropin.write_text(
        "[Container]\n"
        "Secret=kendo_aws_key,type=env,target=AWS_ACCESS_KEY_ID\n"
        "Secret=kendo_aws_secret,type=env,target=AWS_SECRET_ACCESS_KEY\n"
    )
    (host.state / "kendo_aws_key").write_text("AKIA")
    env = host_env(tmp_path)

    out = check(host.src, env, "--quadlet")
    assert out.returncode == 1
    assert "podman secret missing: kendo_aws_secret" in out.stdout

    (host.state / "kendo_aws_secret").write_text("s3cret")
    assert check(host.src, env, "--quadlet").returncode == 0


def test_check_only_warns_when_ufw_will_not_report_without_root(tmp_path):
    # `ufw status` needs root; run as the stack's owner it refuses, which says
    # nothing about whether 80/443 are open.
    home = bundle(tmp_path)
    run(home, *ANSWERS)

    out = check(
        home,
        host_env(
            tmp_path,
            firewall_cmd=None,
            ufw='echo "ERROR: You need to be root to run this script" >&2; exit 1',
        ),
    )

    assert out.returncode == 0, out.stdout
    assert "sudo ufw status" in out.stdout


# ---------------------------------------------------------------- upgrade ---
# `./setup.sh upgrade` (#414): back up, refresh the bundle from the image about
# to run, pull, recreate — and on failure, the exact restore for the backup just
# taken. podman and podman-compose are stubbed; what is asserted is the order
# the script asks them for things in and what it leaves on disk.

UPGRADE_PODMAN_STUB = r"""#!/bin/sh
echo "podman $*" >> "$CALLS"
case "$1" in
  ps) svc=$(echo "$*" | sed -n 's/.*compose.service=\([a-z]*\).*/\1/p')
      echo "kendodojo_${svc}_1" ;;
  exec) [ -z "$BACKUP_FAILS" ] || exit 1; echo PGDMP ;;
  volume) echo uploads ;;
  image) echo "ghcr.io/booji/kendodojomanagement@sha256:0ld" ;;
  run) if [ -f "$PULLED" ]; then tar -C "$NEW_BUNDLE" -c .; else tar -C "$PREV_BUNDLE" -c .; fi ;;
  wait) case "$*" in *--condition*) ;; *) echo "${MIGRATE_EXIT:-0}" ;; esac ;;
esac
"""

UPGRADE_COMPOSE_STUB = """#!/bin/sh
echo "podman-compose $*" >> "$CALLS"
[ "$1" != pull ] || touch "$PULLED"
"""


class Upgrade:
    """A configured quick self-host, the bundle the running image carries, and
    the one the next image carries — identical until a test edits one."""

    def __init__(self, tmp_path: Path):
        self.src = bundle(tmp_path)
        run(self.src, *ANSWERS)
        self.prev = bundle(tmp_path / "prev")
        self.new = bundle(tmp_path / "next")
        for home in (self.src, self.prev, self.new):
            for sub in ("bin", "quadlet"):
                shutil.copytree(ROOT / "deploy" / sub, home / "deploy" / sub)
            shutil.copy(ROOT / "docker-compose.yml", home)
        stubs = tmp_path / "upgrade-bin"
        stubs.mkdir()
        for name, body in (
            ("podman", UPGRADE_PODMAN_STUB),
            ("podman-compose", UPGRADE_COMPOSE_STUB),
        ):
            (stubs / name).write_text(body)
            (stubs / name).chmod(0o755)
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.log = tmp_path / "calls.log"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{stubs}:{os.environ['PATH']}",
            "CALLS": str(self.log),
            "PREV_BUNDLE": str(self.prev),
            "NEW_BUNDLE": str(self.new),
            "PULLED": str(tmp_path / "pulled"),
        }

    def run(self, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.src / "setup.sh"), "upgrade"],
            capture_output=True,
            text=True,
            cwd=self.src,
            env={**self.env, **env},
            check=False,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def first(self, prefix: str) -> int:
        return next(i for i, c in enumerate(self.calls()) if c.startswith(prefix))


def test_upgrade_backs_up_the_database_and_uploads_before_it_pulls(tmp_path):
    up = Upgrade(tmp_path)

    out = up.run()

    assert out.returncode == 0, out.stdout + out.stderr
    calls = up.calls()
    assert "podman exec kendodojo_db_1 pg_dump -U kendo -d kendo -Fc" in calls
    assert "podman volume export kendodojo_static_uploads" in calls
    # A floating tag like :1 changes image, not YAML, and podman-compose only
    # recreates on a YAML change — without --force-recreate the old image
    # keeps running.
    assert (
        up.first("podman exec")
        < up.first("podman-compose pull")
        < up.first("podman-compose up -d --force-recreate")
    )
    [dump] = (up.home / "backups").glob("kendo-*.dump")
    [uploads] = (up.home / "backups").glob("kendo-uploads-*.tar")
    assert str(dump) in out.stdout
    assert str(uploads) in out.stdout


def test_upgrade_never_pulls_without_the_backup_it_just_took(tmp_path):
    up = Upgrade(tmp_path)

    out = up.run(BACKUP_FAILS="1")

    assert out.returncode == 1
    assert "nothing was upgraded" in out.stderr
    assert not any(c.startswith("podman-compose pull") for c in up.calls())


def test_upgrade_takes_the_bundle_from_the_image_about_to_run(tmp_path):
    # Config and image on one version axis: a stale compose file must not drive
    # a new app. The operator's own files are never in play.
    up = Upgrade(tmp_path)
    old_compose = (up.src / "docker-compose.yml").read_text()
    (up.new / "docker-compose.yml").write_text(old_compose + "# next release\n")
    unit = up.new / "deploy/quadlet/kendo-app.container"
    unit.write_text(unit.read_text() + "# next release\n")
    # What a contributor's own build could carry: filled-in files.
    (up.new / ".env").write_text("JWT_SECRET=from-the-image\n")
    (up.new / SELFHOST / "traefik.yml").write_text("from: the-image\n")
    ours = {
        f: (up.src / f).read_text() for f in (".env", str(SELFHOST / "traefik.yml"))
    }

    out = up.run()

    assert out.returncode == 0, out.stdout + out.stderr
    pulled = up.first("podman-compose pull")
    recreated = up.first("podman-compose up -d --force-recreate")
    assert (
        "podman run --rm ghcr.io/booji/kendodojomanagement:1 init"
        in (up.calls()[pulled:recreated])
    )
    assert "# next release" in (up.src / "docker-compose.yml").read_text()
    assert (up.src / "docker-compose.yml.bak").read_text() == old_compose
    assert "docker-compose.yml" in out.stdout
    assert "deploy/quadlet/kendo-app.container" in out.stdout
    assert "setup.sh" not in out.stdout.replace("./setup.sh", "")
    for f, text in ours.items():
        assert (up.src / f).read_text() == text, f


def test_a_failed_migration_prints_the_exact_restore_for_the_backup_just_taken(
    tmp_path,
):
    # podman-compose treats service_completed_successfully as "stopped", so a
    # failed migrate does not fail `up` — the exit code has to be read here.
    up = Upgrade(tmp_path)

    out = up.run(MIGRATE_EXIT="1")

    assert out.returncode == 1
    [dump] = (up.home / "backups").glob("kendo-*.dump")
    [uploads] = (up.home / "backups").glob("kendo-uploads-*.tar")
    assert (
        "KENDO_DB_CONTAINER=kendodojo_db_1 KENDO_UPLOADS_VOLUME=kendodojo_static_uploads"
        f" bash deploy/bin/kendo-restore.sh {dump} {uploads}"
    ) in out.stderr
    # Restoring the data is half a rollback: the new image would migrate it
    # straight back up. The digest pins the image that was running.
    assert "KENDO_IMAGE=ghcr.io/booji/kendodojomanagement@sha256:0ld" in out.stderr


def test_a_failed_upgrade_names_the_encrypted_backup_and_the_key_it_needs(
    tmp_path,
):
    # With a backup key (#500) the artefacts end in .age; the rollback has to
    # name them, and the operator needs the key in hand to use it.
    _, public = keypair()
    up = Upgrade(tmp_path)
    config = up.home / ".config/kendo/backup.env"
    config.parent.mkdir(parents=True)
    config.write_text(f"KENDO_BACKUP_RECIPIENT={public}\n")

    out = up.run(MIGRATE_EXIT="1")

    assert out.returncode == 1
    [dump] = (up.home / "backups").glob("kendo-*.dump.age")
    [uploads] = (up.home / "backups").glob("kendo-uploads-*.tar.age")
    assert f"bash deploy/bin/kendo-restore.sh {dump} {uploads}" in out.stderr
    assert "backup key" in out.stderr


BYO_MOUNT = "      - ./deploy/certs:/etc/traefik/certs:ro\n"


def with_byo_mount(compose: str) -> str:
    return compose.replace(
        "      - traefik_acme:/acme\n", "      - traefik_acme:/acme\n" + BYO_MOUNT
    )


def test_upgrade_stops_before_recreating_over_an_edited_compose_file(tmp_path):
    # The BYO certificate mount is the operator's own edit to
    # docker-compose.yml; replacing the file and recreating would bring the
    # proxy back on Traefik's self-signed default.
    up = Upgrade(tmp_path)
    compose = up.src / "docker-compose.yml"
    compose.write_text(with_byo_mount(compose.read_text()))
    shipped = (up.new / "docker-compose.yml").read_text() + "# next release\n"
    (up.new / "docker-compose.yml").write_text(shipped)
    edited = compose.read_text()

    out = up.run()

    assert out.returncode == 1
    assert compose.read_text() == edited
    assert (up.src / "docker-compose.yml.new").read_text() == shipped
    assert "docker-compose.yml.new" in out.stderr
    assert not any("--force-recreate" in c for c in up.calls())

    # Merged by hand; the re-run takes it as read and carries on.
    compose.write_text(with_byo_mount(shipped))
    again = up.run()

    assert again.returncode == 0, again.stdout + again.stderr
    assert compose.read_text() == with_byo_mount(shipped)
    assert not (up.src / "docker-compose.yml.new").exists()
    assert "podman-compose up -d --force-recreate" in up.calls()


def test_upgrade_keeps_an_edited_file_the_release_did_not_change(tmp_path):
    up = Upgrade(tmp_path)
    compose = up.src / "docker-compose.yml"
    compose.write_text(with_byo_mount(compose.read_text()))
    edited = compose.read_text()

    out = up.run()

    assert out.returncode == 0, out.stdout + out.stderr
    assert compose.read_text() == edited
    assert "Deployment bundle unchanged" in out.stdout


# ------------------------------------------------------------- backup-key ---
# `./setup.sh backup-key` (#500): a new backup key, shown once and confirmed,
# of which only the public half is kept. age-keygen is stubbed to hand out a
# real key the test already knows, so the test can type the confirmation; `-y`
# goes to the real one.

KEYGEN_STUB = """#!/bin/sh
[ "$1" = -y ] && exec "$REAL_AGE_KEYGEN" -y
printf '# created: now\\n# public key: %s\\n%s\\n' "$KEY_PUBLIC" "$KEY_SECRET"
"""


def rotate(up: Upgrade, *answers: str, **env: str) -> subprocess.CompletedProcess:
    secret, public = up.key
    return subprocess.run(
        ["bash", str(up.src / "setup.sh"), "backup-key"],
        input="".join(f"{a}\n" for a in answers),
        capture_output=True,
        text=True,
        cwd=up.src,
        env={**up.env, "KEY_SECRET": secret, "KEY_PUBLIC": public, **env},
        check=False,
    )


def with_keygen(up: Upgrade) -> Upgrade:
    stub = up.log.parent / "upgrade-bin/age-keygen"
    stub.write_text(KEYGEN_STUB)
    stub.chmod(0o755)
    up.env["REAL_AGE_KEYGEN"] = shutil.which("age-keygen")
    up.key = keypair()
    return up


def test_backup_key_confirms_the_saved_key_then_backs_up_under_it(tmp_path):
    up = with_keygen(Upgrade(tmp_path))
    secret, public = up.key
    backups = up.home / "backups"
    backups.mkdir()
    (backups / "kendo-20260101-000000.dump").write_text("old")

    out = rotate(up, "WRONG1", secret[-6:], "y")

    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.count(secret) == 1
    assert "does not match" in out.stdout
    config = (up.home / ".config/kendo/backup.env").read_text()
    assert f"KENDO_BACKUP_RECIPIENT={public}" in config
    assert no_file_holds(tmp_path, secret)
    # A backup under the new key at once, so a lost key costs nothing more.
    [dump] = backups.glob("kendo-*.dump.age")
    (tmp_path / "scratch").mkdir()
    assert decrypt(dump, secret, tmp_path / "scratch") == "PGDMP\n"
    assert not (backups / "kendo-20260101-000000.dump").exists()


def test_giving_up_on_the_confirmation_keeps_the_old_key(tmp_path):
    up = with_keygen(Upgrade(tmp_path))
    config = up.home / ".config/kendo/backup.env"
    config.parent.mkdir(parents=True)
    config.write_text("KENDO_BACKUP_RECIPIENT=age1old\n")

    out = rotate(up, "")

    assert out.returncode == 1
    assert config.read_text() == "KENDO_BACKUP_RECIPIENT=age1old\n"
    assert not any(c.startswith("podman exec") for c in up.calls())


def test_a_failed_backup_after_a_new_key_touches_nothing_older(tmp_path):
    # Deleting the old backups with no new one to stand in for them would
    # leave nothing to restore.
    up = with_keygen(Upgrade(tmp_path))
    secret, public = up.key
    backups = up.home / "backups"
    backups.mkdir()
    (backups / "kendo-20260101-000000.dump").write_text("old")

    out = rotate(up, secret[-6:], "y", BACKUP_FAILS="1")

    assert out.returncode == 1
    assert "The new key is set" in out.stderr
    assert "bash deploy/bin/kendo-backup.sh" in out.stderr
    assert public in (up.home / ".config/kendo/backup.env").read_text()
    assert (backups / "kendo-20260101-000000.dump").exists()


def test_older_backups_are_kept_unless_the_operator_says_delete(tmp_path):
    up = with_keygen(Upgrade(tmp_path))
    secret, _ = up.key
    backups = up.home / "backups"
    backups.mkdir()
    (backups / "kendo-20260101-000000.dump").write_text("old")

    out = rotate(up, secret[-6:])

    assert out.returncode == 0, out.stdout + out.stderr
    assert "kendo-20260101-000000.dump" in out.stdout
    assert (backups / "kendo-20260101-000000.dump").exists()


def test_install_offers_a_backup_key_and_a_rerun_keeps_it(tmp_path):
    host = Host(tmp_path)
    secret, public = keypair()
    stub = tmp_path / "bin/age-keygen"
    stub.write_text(KEYGEN_STUB)
    stub.chmod(0o755)
    host.env |= {
        "REAL_AGE_KEYGEN": shutil.which("age-keygen"),
        "KEY_SECRET": secret,
        "KEY_PUBLIC": public,
    }

    # At a terminal, as an operator would be: script(1) gives setup.sh a pty.
    command = f"bash {host.src / 'setup.sh'} --quadlet"
    answers = ("dojo.example.com", "1", "1", "admin@example.com", "", secret[-6:])
    out = subprocess.run(
        ["script", "-qec", command, "/dev/null"],
        input="".join(f"{a}\n" for a in answers),
        capture_output=True,
        text=True,
        cwd=host.src,
        env=host.env,
        check=False,
    )
    assert out.returncode == 0, out.stdout

    config = host.home / ".config/kendo/backup.env"
    assert config.read_text() == f"KENDO_BACKUP_RECIPIENT={public}\n"
    assert no_file_holds(tmp_path, secret)

    again = host.run("dojo.example.com", "1", "1", "admin@example.com")
    assert "kept the existing backup key" in again.stdout
    assert config.read_text() == f"KENDO_BACKUP_RECIPIENT={public}\n"


def test_a_piped_install_never_offers_a_backup_key(tmp_path):
    # A scripted install's stdout is a log, not a person: a key printed there
    # lands on disk, and the confirmation it waits for never comes.
    host = Host(tmp_path)

    out = host.run("dojo.example.com", "1", "1", "admin@example.com", "", "")

    assert "AGE-SECRET-KEY-" not in out.stdout
    assert "setup.sh backup-key --quadlet" in out.stdout
    assert not (host.home / ".config/kendo/backup.env").exists()


def test_backup_key_refuses_while_the_environment_pins_a_recipient(tmp_path):
    # A recipient in the environment wins over backup.env, so the "new" key
    # would never be used — not by the backup taken now, nor any after it.
    up = with_keygen(Upgrade(tmp_path))
    secret, _ = up.key

    out = rotate(up, secret[-6:], KENDO_BACKUP_RECIPIENT="age1pinned")

    assert out.returncode == 1
    assert "KENDO_BACKUP_RECIPIENT" in out.stderr
    assert secret not in out.stdout
    assert not (up.home / ".config/kendo/backup.env").exists()


def test_quadlet_backup_key_refreshes_the_script_the_timer_runs(tmp_path):
    # The timer runs ~/.local/bin/kendo-backup.sh, copied at install: a copy
    # from before #500 would ignore the key and go on writing plaintext.
    host = Host(tmp_path)
    secret, public = keypair()
    stub = tmp_path / "bin/age-keygen"
    stub.write_text(KEYGEN_STUB)
    stub.chmod(0o755)
    installed = host.home / ".local/bin/kendo-backup.sh"
    installed.parent.mkdir(parents=True)
    installed.write_text("#!/bin/sh\necho old copy\n")

    out = subprocess.run(
        ["bash", str(host.src / "setup.sh"), "backup-key", "--quadlet"],
        input=f"{secret[-6:]}\n",
        capture_output=True,
        text=True,
        cwd=host.src,
        env={
            **host.env,
            "REAL_AGE_KEYGEN": shutil.which("age-keygen"),
            "KEY_SECRET": secret,
            "KEY_PUBLIC": public,
        },
        check=False,
    )

    assert out.returncode == 0, out.stdout + out.stderr
    assert installed.read_text() == (ROOT / "deploy/bin/kendo-backup.sh").read_text()
    assert list((host.home / "backups").glob("kendo-*.dump.age"))
