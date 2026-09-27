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


def env_of(home: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in (home / ".env").read_text().splitlines()
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
