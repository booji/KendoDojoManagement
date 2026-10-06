"""Behavioural tests for `deploy/bin/kendo-backup.sh` (#500) and
`deploy/bin/kendo-restore.sh` (#501).

The dumps hold every Member's personal data, so with a backup key configured
nothing readable may reach the backup directory: each artefact is encrypted to
the key's public half in the pipeline. Restore takes the private half pasted
at a prompt and decrypts in a pipe, so neither the key nor the plaintext lands
on disk. podman is stubbed on PATH, recording what it is asked to restore; age
is real.
"""

import os
import subprocess
from pathlib import Path

from tests.backup_support import decrypt, keypair, no_file_holds

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)

PODMAN_STUB = """#!/bin/sh
echo "$*" >> "$PODMAN_CALLS"
case "$*" in
  *pg_dump*) echo PGDMP ;;
  "volume export"*) echo uploads ;;
  *pg_restore*) cat > "$RESTORED/db" ;;
  "volume import"*) cat > "$RESTORED/uploads" ;;
  *) cat > /dev/null ;;
esac
"""


class Backup:
    """A fake HOME and a stubbed podman around the real backup and restore
    scripts. What the stub was asked to restore lands in ``restored``."""

    def __init__(self, tmp_path: Path):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.dir = self.home / "backups"
        self.tmp = tmp_path / "tmp"
        self.tmp.mkdir()
        self.restored = tmp_path / "restored"
        self.restored.mkdir()
        self.calls = tmp_path / "podman.log"
        stubs = tmp_path / "bin"
        stubs.mkdir()
        (stubs / "podman").write_text(PODMAN_STUB)
        (stubs / "podman").chmod(0o755)
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{stubs}:{os.environ['PATH']}",
            "PODMAN_CALLS": str(self.calls),
            "RESTORED": str(self.restored),
            # Inside tmp_path, so a key or plaintext spilled to a temp file is
            # caught by the scans below.
            "TMPDIR": str(self.tmp),
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

    def restore(self, *files: Path, answers: str) -> subprocess.CompletedProcess:
        self.calls.unlink(missing_ok=True)
        return subprocess.run(
            ["bash", str(ROOT / "deploy/bin/kendo-restore.sh"), *map(str, files)],
            input=answers,
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

    def podman_calls(self) -> list[str]:
        return self.calls.read_text().splitlines() if self.calls.exists() else []


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


def test_restore_decrypts_an_encrypted_backup_with_a_pasted_key(tmp_path):
    secret, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public)
    backup.run()
    [dump] = backup.dir.glob("kendo-*.dump.age")
    [uploads] = backup.dir.glob("kendo-uploads-*.tar.age")

    out = backup.restore(dump, uploads, answers=f"{secret}\nyes\n")

    assert out.returncode == 0, out.stderr
    assert (backup.restored / "db").read_text() == "PGDMP\n"
    assert (backup.restored / "uploads").read_text() == "uploads\n"
    assert "volume import kendo-app-uploads -" in backup.podman_calls()
    # Decrypted in a pipe: no key file anywhere, and nothing decrypted beside
    # the backup or in a temp directory.
    assert no_file_holds(tmp_path, secret)
    assert sorted(backup.dir.iterdir()) == sorted([dump, uploads])
    assert list(backup.tmp.iterdir()) == []


def test_a_wrong_key_stops_the_restore_before_the_database_is_dropped(tmp_path):
    _, public = keypair()
    other, _ = keypair()
    backup = Backup(tmp_path)
    backup.configure(public)
    backup.run()
    [dump] = backup.dir.glob("kendo-*.dump.age")

    out = backup.restore(dump, answers=f"{other}\nyes\n")

    assert out.returncode == 1
    assert "encrypted with a different key" in out.stderr
    assert backup.podman_calls() == []


def test_a_truncated_backup_stops_the_restore_before_the_database_is_dropped(
    tmp_path,
):
    # Decrypting straight into pg_restore would only notice the missing tail
    # after the DROP; the whole file is checked first.
    secret, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public)
    backup.run()
    [dump] = backup.dir.glob("kendo-*.dump.age")
    dump.write_bytes(dump.read_bytes()[:-20])

    out = backup.restore(dump, answers=f"{secret}\nyes\n")

    assert out.returncode == 1
    assert "nothing was changed" in out.stderr
    assert backup.podman_calls() == []


def test_a_plaintext_backup_restores_without_asking_for_a_key(tmp_path):
    # Backups from before a key was set stay restorable. A key prompt would
    # swallow the "yes" and fail the run, so passing also proves none came.
    backup = Backup(tmp_path)
    backup.run()
    [dump] = backup.dir.glob("kendo-*.dump")
    [uploads] = backup.dir.glob("kendo-uploads-*.tar")

    out = backup.restore(dump, uploads, answers="yes\n")

    assert out.returncode == 0, out.stderr
    assert (backup.restored / "db").read_text() == "PGDMP\n"
    assert (backup.restored / "uploads").read_text() == "uploads\n"


def test_a_mistyped_key_is_named_as_such_before_anything_changes(tmp_path):
    # The likeliest slip: a key copied with a character wrong or missing.
    secret, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public)
    backup.run()
    [dump] = backup.dir.glob("kendo-*.dump.age")

    out = backup.restore(dump, answers=f"{secret[:-1]}\nyes\n")

    assert out.returncode == 1
    assert "not a valid backup key" in out.stderr
    assert backup.podman_calls() == []


def test_a_damaged_uploads_archive_alone_still_stops_the_restore_first(tmp_path):
    secret, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public)
    backup.run()
    [dump] = backup.dir.glob("kendo-*.dump.age")
    [uploads] = backup.dir.glob("kendo-uploads-*.tar.age")
    uploads.write_bytes(uploads.read_bytes()[:-20])

    out = backup.restore(dump, uploads, answers=f"{secret}\nyes\n")

    assert out.returncode == 1
    assert backup.podman_calls() == []


def test_a_restore_failing_after_the_drop_says_the_database_is_now_partial(
    tmp_path,
):
    backup = Backup(tmp_path)
    backup.run()
    [dump] = backup.dir.glob("kendo-*.dump")
    stub = tmp_path / "bin/podman"
    stub.write_text(
        stub.read_text().replace(
            '*pg_restore*) cat > "$RESTORED/db" ;;', "*pg_restore*) exit 1 ;;"
        )
    )

    out = backup.restore(dump, answers="yes\n")

    assert out.returncode == 1
    assert "dropped" in out.stderr
    assert str(dump) in out.stderr
