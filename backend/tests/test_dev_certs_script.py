"""Behavioural tests for `deploy/bin/dev-certs.sh` (issue #379).

The script is the whole of `make certs`, so unlike the static Makefile contract
tests these actually run it: against a throwaway `CERT_DIR` and a stubbed PATH,
so no state on the developer's machine is touched and mkcert need not exist.

What is pinned here is the self-healing contract: a good pair is left alone, a
self-signed pair is reissued once mkcert appears, and the force path reissues
unconditionally. Trust-store installation is not automatable and stays manual.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)
SCRIPT = ROOT / "deploy" / "bin" / "dev-certs.sh"
HOST = "dojo.localhost"

pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None, reason="the script needs openssl to issue a pair"
)


def run(cert_dir: Path, *args: str, path_extra: Path | None = None):
    env = dict(os.environ, CERT_DIR=str(cert_dir))
    if path_extra is not None:
        env["PATH"] = f"{path_extra}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        check=False,
    )


def pair(cert_dir: Path) -> tuple[Path, Path]:
    return cert_dir / f"{HOST}.pem", cert_dir / f"{HOST}-key.pem"


def fake_mkcert(tmp_path: Path) -> Path:
    """A mkcert stub that issues a certificate whose issuer says "mkcert"."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "mkcert"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'while [ $# -gt 0 ]; do case "$1" in\n'
        '  -cert-file) cert="$2"; shift 2;;\n'
        '  -key-file) key="$2"; shift 2;;\n'
        '  *) hosts="${hosts:-} $1"; shift;;\n'
        "esac; done\n"
        'san=$(for h in $hosts; do printf "DNS:%s," "$h"; done)\n'
        "openssl req -x509 -newkey rsa:2048 -nodes -days 825 \\\n"
        '  -subj "/CN=mkcert stub" \\\n'
        '  -addext "subjectAltName=${san%,}" \\\n'
        '  -keyout "$key" -out "$cert" 2>/dev/null\n'
    )
    stub.chmod(0o755)
    return bin_dir


def issuer(cert: Path) -> str:
    return subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-issuer"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_issues_a_pair_when_none_exists(tmp_path):
    cert, key = pair(tmp_path)
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert cert.exists() and key.exists()


def test_says_which_generator_it_used_and_that_the_result_is_untrusted(tmp_path):
    output = run(tmp_path).stdout.lower()
    assert "self-signed" in output
    assert "mkcert" in output, (
        "the message must name the next action, not just the state"
    )


def test_a_second_run_leaves_a_usable_pair_alone(tmp_path):
    run(tmp_path)
    cert, key = pair(tmp_path)
    before = (cert.read_bytes(), key.read_bytes())
    run(tmp_path)
    assert (cert.read_bytes(), key.read_bytes()) == before


def test_force_reissues(tmp_path):
    run(tmp_path)
    cert, _ = pair(tmp_path)
    before = cert.read_bytes()
    result = run(tmp_path, "--force")
    assert result.returncode == 0, result.stderr
    assert cert.read_bytes() != before


def test_a_self_signed_pair_is_reissued_once_mkcert_is_available(tmp_path):
    certs = tmp_path / "certs"
    certs.mkdir()
    run(certs)
    cert, _ = pair(certs)
    assert "mkcert" not in issuer(cert)

    result = run(certs, path_extra=fake_mkcert(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "mkcert" in issuer(cert), "an untrusted certificate must repair itself"


def test_an_mkcert_pair_is_not_reissued(tmp_path):
    certs = tmp_path / "certs"
    certs.mkdir()
    stub = fake_mkcert(tmp_path)
    run(certs, path_extra=stub)
    cert, _ = pair(certs)
    before = cert.read_bytes()

    run(certs, path_extra=stub)

    assert cert.read_bytes() == before


def test_a_certificate_missing_the_dev_host_is_reissued(tmp_path):
    """A rename of the dev host must not leave a stale SAN in place."""
    certs = tmp_path / "certs"
    certs.mkdir()
    cert, key = pair(certs)
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "825",
            "-subj",
            "/CN=old.localhost",
            "-addext",
            "subjectAltName=DNS:old.localhost",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        capture_output=True,
        check=True,
    )
    before = cert.read_bytes()

    result = run(certs)

    assert result.returncode == 0, result.stderr
    assert cert.read_bytes() != before
    san = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-ext", "subjectAltName"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert f"DNS:{HOST}" in san


def test_reissuing_over_an_existing_pair_names_the_proxy_restart(tmp_path):
    run(tmp_path)
    output = run(tmp_path, "--force").stdout.lower()
    assert "restart" in output and "proxy" in output


def test_the_key_is_not_world_readable(tmp_path):
    run(tmp_path)
    _, key = pair(tmp_path)
    assert key.stat().st_mode & 0o077 == 0
