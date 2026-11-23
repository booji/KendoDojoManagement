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
import time
from pathlib import Path

import pytest

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

RCLONE_STUB = """#!/bin/sh
echo "$*" >> "$RCLONE_CALLS"
[ -z "$RCLONE_HANGS" ] || exec sleep 60
[ -z "$RCLONE_FAILS" ]
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
        for name, body in (("podman", PODMAN_STUB), ("rclone", RCLONE_STUB)):
            (stubs / name).write_text(body)
            (stubs / name).chmod(0o755)
        self.rclone_log = tmp_path / "rclone.log"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{stubs}:{os.environ['PATH']}",
            "PODMAN_CALLS": str(self.calls),
            "RESTORED": str(self.restored),
            "RCLONE_CALLS": str(self.rclone_log),
            # Inside tmp_path, so a key or plaintext spilled to a temp file is
            # caught by the scans below.
            "TMPDIR": str(self.tmp),
        }

    def configure(self, recipient: str | None = None, **settings: str) -> None:
        """Write backup.env: the recipient, plus any KENDO_BACKUP_<NAME>=."""
        lines = [f"KENDO_BACKUP_RECIPIENT={recipient}"] if recipient else []
        lines += [f"KENDO_BACKUP_{k.upper()}={v}" for k, v in settings.items()]
        config = self.home / ".config/kendo/backup.env"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("".join(f"{line}\n" for line in lines))

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

    def rclone_calls(self) -> list[str]:
        return (
            self.rclone_log.read_text().splitlines() if self.rclone_log.exists() else []
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


def test_a_restore_ends_by_saying_migrate_must_re_run(tmp_path):
    # The restore leaves kendo_app with no grants (#481); only migrate gives
    # them back, so starting the app alone would serve errors.
    backup = Backup(tmp_path)
    backup.run()
    [dump] = backup.dir.glob("kendo-*.dump")
    [uploads] = backup.dir.glob("kendo-uploads-*.tar")

    out = backup.restore(dump, uploads, answers="yes\n")

    assert out.returncode == 0, out.stderr
    after_uploads = out.stdout[out.stdout.index("uploads restored from:") :]
    assert "systemctl --user restart kendo-migrate kendo-app" in after_uploads
    # Stopping kendo-app for the restore stopped Traefik too (Requires=), and
    # restarting the app does not start it again (#628).
    assert "systemctl --user start kendo-traefik" in after_uploads
    assert "podman-compose up -d --force-recreate" in after_uploads


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


def test_a_restore_onto_a_server_without_the_app_role_completes_with_uploads(
    tmp_path,
):
    # A dump carries GRANTs to kendo_app (#453). On a fresh server, where
    # kendo-migrate has not yet created that role, pg_restore errors on them
    # unless privileges are skipped; kendo-migrate re-applies them after (#481).
    backup = Backup(tmp_path)
    backup.run()
    [dump] = backup.dir.glob("kendo-*.dump")
    [uploads] = backup.dir.glob("kendo-uploads-*.tar")
    stub = tmp_path / "bin/podman"
    original = stub.read_text()
    patched = original.replace(
        '*pg_restore*) cat > "$RESTORED/db" ;;',
        '*pg_restore*--no-privileges*) cat > "$RESTORED/db" ;;\n'
        "  *pg_restore*) echo 'role \"kendo_app\" does not exist' >&2; exit 1 ;;",
    )
    assert patched != original, "the podman stub's pg_restore case has moved"
    stub.write_text(patched)

    out = backup.restore(dump, uploads, answers="yes\n")

    assert out.returncode == 0, out.stderr
    assert (backup.restored / "db").read_text() == "PGDMP\n"
    assert (backup.restored / "uploads").read_text() == "uploads\n"


# ---------------------------------------------------------------- off-site ---
# An optional rclone copy of each run's encrypted artefacts (#502). rclone is
# stubbed: what is asserted is what it was asked to copy and delete.


def test_without_a_remote_the_backup_says_so_and_calls_no_rclone(tmp_path):
    backup = Backup(tmp_path)

    out = backup.run()

    assert out.returncode == 0, out.stderr
    assert "No off-site copy configured" in out.stdout
    assert backup.rclone_calls() == []


def test_a_remote_gets_every_recent_encrypted_artefact_and_never_plaintext(
    tmp_path,
):
    # The whole directory, filtered: a copy that failed last night goes up
    # with tonight's (rclone skips what the remote already has), while older
    # plaintext backups from before the key never match the filter.
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.dir.mkdir()
    (backup.dir / "kendo-20260101-000000.dump").write_text("plaintext")
    backup.configure(public, remote="gdrive:kendo-backups")
    week_ago = time.time() - 8 * 86400
    os.utime(backup.home / ".config/kendo/backup.env", (week_ago, week_ago))

    out = backup.run()

    assert out.returncode == 0, out.stderr
    assert backup.rclone_calls() == [
        f"copy {backup.dir} gdrive:kendo-backups --max-depth 1"
        " --include kendo-*.age --max-age 604800s"
    ]


def test_the_catch_up_window_never_reaches_past_keep_days(tmp_path):
    # Otherwise a copy expired on the remote is uploaded again the next night,
    # only to be expired again.
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote="gdrive:kendo-backups", remote_keep_days="3")
    week_ago = time.time() - 8 * 86400
    os.utime(backup.home / ".config/kendo/backup.env", (week_ago, week_ago))

    out = backup.run()

    assert out.returncode == 0, out.stderr
    [copy, delete] = backup.rclone_calls()
    assert copy.endswith(" --max-age 259200s")
    assert " --min-age 3d " in delete


def test_a_remote_without_a_key_uploads_nothing_and_says_why(tmp_path):
    backup = Backup(tmp_path)
    backup.configure(remote="gdrive:kendo-backups")

    out = backup.run()

    assert out.returncode == 0, out.stderr
    assert backup.rclone_calls() == []
    assert "Off-site copy to gdrive:kendo-backups is skipped" in out.stderr
    assert list(backup.dir.glob("kendo-*.dump"))


def test_keep_days_expires_only_old_kendo_artefacts_on_the_remote(tmp_path):
    # The remote may be a shared folder: nothing but our own encrypted
    # artefacts, and nothing below it, is ever deleted.
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote="gdrive:kendo-backups", remote_keep_days="90")

    out = backup.run()

    assert out.returncode == 0, out.stderr
    calls = backup.rclone_calls()
    assert calls[-1] == (
        "delete gdrive:kendo-backups --min-age 90d --max-depth 1 --include kendo-*.age"
    )
    assert [c.split()[0] for c in calls] == ["copy", "delete"]


def test_a_failed_upload_keeps_the_local_backup_and_exits_75(tmp_path):
    # 75 (EX_TEMPFAIL), not 1: the backup itself is complete, and setup.sh tells
    # the two apart. A code nothing in the local half can exit with by accident.
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote="gdrive:kendo-backups")

    out = backup.run(RCLONE_FAILS="1")

    assert out.returncode == 75
    assert "gdrive:kendo-backups" in out.stderr
    assert "local backup" in out.stderr
    assert list(backup.dir.glob("kendo-*.dump.age"))
    assert list(backup.dir.glob("kendo-uploads-*.tar.age"))


def test_a_remote_with_no_rclone_installed_names_the_setting(tmp_path):
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote="gdrive:kendo-backups")
    (tmp_path / "bin/rclone").unlink()

    out = backup.run()

    assert out.returncode == 75
    assert "KENDO_BACKUP_REMOTE" in out.stderr
    assert "rclone" in out.stderr
    assert list(backup.dir.glob("kendo-*.dump.age"))


def test_keep_days_that_is_not_a_number_deletes_nothing(tmp_path):
    # It reaches `rclone delete --min-age`; a typo there must not become a
    # wider deletion than the operator meant.
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(
        public, remote="gdrive:kendo-backups", remote_keep_days="90 --dry-run=false"
    )

    out = backup.run()

    assert out.returncode == 75
    assert "KENDO_BACKUP_REMOTE_KEEP_DAYS" in out.stderr
    assert not any(c.startswith("delete") for c in backup.rclone_calls())


def test_a_remote_that_is_not_an_rclone_remote_is_refused(tmp_path):
    # A local path would pass to rclone and have `delete` expire this host's
    # own backups; a leading - would be read as a flag.
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote=str(backup.dir), remote_keep_days="1")

    out = backup.run()

    assert out.returncode == 75
    assert "KENDO_BACKUP_REMOTE" in out.stderr
    assert backup.rclone_calls() == []
    assert list(backup.dir.glob("kendo-*.dump.age"))


def test_backup_env_values_survive_quotes_comments_and_crlf(tmp_path):
    # backup.env looks like a shell env file, so it gets written like one:
    # quoted, commented, or saved on Windows. None of that is the value.
    _, public = keypair()
    backup = Backup(tmp_path)
    config = backup.home / ".config/kendo/backup.env"
    config.parent.mkdir(parents=True)
    config.write_bytes(
        (
            f"KENDO_BACKUP_RECIPIENT='{public}'\r\n"
            'KENDO_BACKUP_REMOTE="gdrive:kendo-backups"   # the club Drive\r\n'
            "KENDO_BACKUP_REMOTE_KEEP_DAYS=90 # about three months\r\n"
        ).encode()
    )

    out = backup.run()

    assert out.returncode == 0, out.stderr
    assert list(backup.dir.glob("kendo-*.dump.age"))
    calls = backup.rclone_calls()
    assert all(" gdrive:kendo-backups" in c for c in calls), calls
    assert calls[-1].startswith("delete gdrive:kendo-backups --min-age 90d ")


def test_a_hung_remote_is_cut_off_and_reported_as_an_off_site_failure(tmp_path):
    # A stalled upload would otherwise hold the oneshot unit "activating"
    # forever: no next night's backup, and `setup.sh upgrade` waiting on it.
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote="gdrive:kendo-backups", remote_timeout="1s")

    started = time.monotonic()
    out = backup.run(RCLONE_HANGS="1")

    assert time.monotonic() - started < 30
    assert out.returncode == 75
    assert "did not finish within 1s" in out.stderr
    assert list(backup.dir.glob("kendo-*.dump.age"))


def test_a_timeout_that_is_not_a_duration_is_refused(tmp_path):
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote="gdrive:kendo-backups", remote_timeout="1 hour")

    out = backup.run()

    assert out.returncode == 75
    assert "KENDO_BACKUP_REMOTE_TIMEOUT" in out.stderr
    assert backup.rclone_calls() == []


@pytest.mark.parametrize(
    "remote",
    [
        "gdrive:kendo-backups",
        "b2,hard_delete=true:kendo-bucket",
        ":s3,provider=Cloudflare,env_auth=true:kendo-bucket",
        "my nas:backups",
    ],
)
def test_any_rclone_remote_form_is_accepted(tmp_path, remote):
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote=remote)

    out = backup.run()

    assert out.returncode == 0, out.stderr
    assert [c.split(" ")[0] for c in backup.rclone_calls()] == ["copy"]


@pytest.mark.parametrize(
    "remote",
    [
        "/mnt/nas:backups",
        "./backups:old",
        "-x:y",
        ":local:/home/kendo",
        ":alias,remote=/home/kendo/backups:",
        '"gdrive:kendo-backups',
    ],
)
def test_a_local_path_or_flag_is_never_taken_for_a_remote(tmp_path, remote):
    # Each would reach the local disk (or rclone's flags), and the expiry
    # would delete there.
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote=remote, remote_keep_days="1")

    out = backup.run()

    assert out.returncode == 75, out.stderr
    assert "KENDO_BACKUP_REMOTE" in out.stderr
    assert backup.rclone_calls() == []


def test_catch_up_never_reaches_back_past_the_last_change_to_backup_env(tmp_path):
    # A new key rewrites backup.env. Copies under the old key that the
    # operator deleted off-site after a leak must not be sent back up.
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote="gdrive:kendo-backups")
    day_ago = time.time() - 86400
    os.utime(backup.home / ".config/kendo/backup.env", (day_ago, day_ago))

    out = backup.run()

    assert out.returncode == 0, out.stderr
    [copy] = backup.rclone_calls()
    window = int(copy.rsplit(" --max-age ", 1)[1].removesuffix("s"))
    assert 86400 <= window < 86400 + 60


def test_a_quoted_value_keeps_a_hash_inside_its_quotes(tmp_path):
    _, public = keypair()
    backup = Backup(tmp_path)
    backup.configure(public, remote='"gdrive:Club #1"  # the club Drive')

    out = backup.run()

    assert out.returncode == 0, out.stderr
    [copy] = backup.rclone_calls()
    assert " gdrive:Club #1 --max-depth 1 " in copy
