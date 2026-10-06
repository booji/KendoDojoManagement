"""Behavioural tests for `deploy/bin/kendo-backup.sh` (issue #500).

The dumps hold every Member's personal data, so with a backup key configured
nothing readable may reach the backup directory: each artefact is encrypted to
the key's public half in the pipeline. podman is stubbed on PATH; age is real,
so what is asserted is that the file on disk decrypts with the private half.
"""

import os
import subprocess
from pathlib import Path

from tests.backup_support import decrypt, keypair

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)

PODMAN_STUB = """#!/bin/sh
case "$1" in
  exec) echo PGDMP ;;
  volume) echo uploads ;;
esac
"""


class Backup:
    """A fake HOME and a stubbed podman around the real backup script."""

    def __init__(self, tmp_path: Path):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.dir = self.home / "backups"
        stubs = tmp_path / "bin"
        stubs.mkdir()
        (stubs / "podman").write_text(PODMAN_STUB)
        (stubs / "podman").chmod(0o755)
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{stubs}:{os.environ['PATH']}",
        }

    def configure(self, recipient: str) -> None:
        config = self.home / ".config/kendo/backup.env"
        config.parent.mkdir(parents=True)
        config.write_text(f"KENDO_BACKUP_RECIPIENT={recipient}\n")

    def run(self, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(ROOT / "deploy/bin/kendo-backup.sh")],
            capture_output=True,
            text=True,
            env={**self.env, **env},
            check=False,
        )


def test_a_configured_key_leaves_only_encrypted_artefacts(tmp_path):
    secret, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public)

    out = backup.run()

    assert out.returncode == 0, out.stderr
    [dump] = backup.dir.glob("kendo-*.dump.age")
    [uploads] = backup.dir.glob("kendo-uploads-*.tar.age")
    assert sorted(p.name for p in backup.dir.iterdir()) == sorted(
        [dump.name, uploads.name]
    )
    assert decrypt(dump, secret, tmp_path) == "PGDMP\n"
    assert decrypt(uploads, secret, tmp_path) == "uploads\n"
    assert f"written: {dump} (" in out.stdout


def test_without_a_key_it_still_backs_up_but_says_it_is_unencrypted(tmp_path):
    # No backup is worse than a plaintext one, and an install from before #500
    # has no key: failing here would break every nightly timer on upgrade.
    backup = Backup(tmp_path)

    out = backup.run()

    assert out.returncode == 0, out.stderr
    [dump] = backup.dir.glob("kendo-*.dump")
    assert dump.read_text() == "PGDMP\n"
    assert not list(backup.dir.glob("*.age"))
    assert "not encrypted" in out.stderr
    assert "setup.sh backup-key" in out.stderr


def test_prune_counts_plaintext_and_encrypted_backups_together(tmp_path):
    # Plaintext backups from before the key was set must age out like any
    # other, not sit beside the encrypted ones forever.
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.dir.mkdir()
    old = []
    for n, name in enumerate(
        ["kendo-20260101-000000.dump", "kendo-20260102-000000.dump"]
        + ["kendo-uploads-20260101-000000.tar", "kendo-uploads-20260102-000000.tar"]
    ):
        path = backup.dir / name
        path.write_text("old")
        os.utime(path, (1_700_000_000 + n % 2, 1_700_000_000 + n % 2))
        old.append(path)
    backup.configure(public)

    out = backup.run(KENDO_BACKUP_KEEP="2")

    assert out.returncode == 0, out.stderr
    left = sorted(p.name for p in backup.dir.iterdir())
    # The newest two of each kind: this run's encrypted one and the newer
    # plaintext one.
    assert len(left) == 4, left
    assert "kendo-20260102-000000.dump" in left
    assert "kendo-uploads-20260102-000000.tar" in left
    assert not (backup.dir / "kendo-20260101-000000.dump").exists()
    assert not (backup.dir / "kendo-uploads-20260101-000000.tar").exists()


def test_restore_refuses_an_encrypted_backup_before_touching_the_database(
    tmp_path,
):
    # kendo-restore.sh drops the database before pg_restore runs; fed
    # ciphertext, that is a dropped database and a failed restore.
    backup = Backup(tmp_path)
    calls = tmp_path / "calls.log"
    (tmp_path / "bin/podman").write_text(f'#!/bin/sh\necho "$*" >> {calls}\n')
    dump = tmp_path / "kendo-20260101-000000.dump.age"
    dump.write_text("ciphertext")

    out = subprocess.run(
        ["bash", str(ROOT / "deploy/bin/kendo-restore.sh"), str(dump)],
        input="yes\n",
        capture_output=True,
        text=True,
        env=backup.env,
        check=False,
    )

    assert out.returncode == 1
    assert "age -d" in out.stderr
    assert not calls.exists()
