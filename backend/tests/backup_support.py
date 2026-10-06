"""Shared helpers for the backup encryption tests (#500): a real age key pair,
and decrypting an artefact with its private half."""

import subprocess
from pathlib import Path


def keypair() -> tuple[str, str]:
    """A real age identity and its recipient."""
    secret = next(
        line
        for line in subprocess.run(
            ["age-keygen"], capture_output=True, text=True, check=True
        ).stdout.splitlines()
        if line.startswith("AGE-SECRET-KEY-")
    )
    public = subprocess.run(
        ["age-keygen", "-y"], input=secret, capture_output=True, text=True, check=True
    ).stdout.strip()
    return secret, public


def decrypt(path: Path, secret: str, tmp_path: Path) -> str:
    identity = tmp_path / "identity.txt"
    identity.write_text(secret + "\n")
    return subprocess.run(
        ["age", "-d", "-i", str(identity), str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
