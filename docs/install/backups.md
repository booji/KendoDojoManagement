# Backups (as `kendo`)

Nightly backup to `~/backups`, keeping the newest 14 of each artefact, driven by a systemd user timer. Each run writes two files sharing one timestamp:

| File | Contents |
| --- | --- |
| `kendo-<stamp>.dump` | Postgres, `pg_dump` custom format |
| `kendo-uploads-<stamp>.tar` | the `kendo-app-uploads` volume — logos and login backgrounds |

Uploaded images live on a volume, not in the database, so the dump alone does not cover them. With a [backup key](#the-backup-key) set, both are encrypted and end in `.age`: `kendo-<stamp>.dump.age`, `kendo-uploads-<stamp>.tar.age`.

The Quick self-host (Compose) stack has no nightly timer. It takes a backup to `~/backups` on every `./setup.sh upgrade`, and the backup key and off-site settings below apply to it too — run `./setup.sh backup-key` without `--quadlet`.

`./setup.sh --quadlet` installs `kendo-backup.service` and `kendo-backup.timer` in `~/.config/systemd/user/` and enables the timer: the first backup runs at the timer's next `OnCalendar=` (02:30 as shipped). Without `setup.sh`, the same by hand:

```bash
cp deploy/systemd/kendo-backup.service ~/.config/systemd/user/
cp deploy/systemd/kendo-backup.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kendo-backup.timer
```

Either way, check the schedule and take one now:

```bash
systemctl --user list-timers kendo-backup.timer --no-pager
systemctl --user start kendo-backup.service
ls -lh ~/backups
```

`./setup.sh check --quadlet` warns when backups are not encrypted, when an off-site copy is not set up or would be refused, when the newest backup is two or more days old, and when the last run failed — including a failed off-site copy, which leaves the local backup fresh.

## The backup key

Backups hold every Member's personal data, including under-18 and safeguarding data, so they are encrypted with [`age`](https://github.com/FiloSottile/age). Install offers to set a key; to set one later, or replace one, run from the deployment bundle:

```bash
sudo dnf install -y age   # or: sudo apt install -y age
./setup.sh backup-key --quadlet
```

It shows the private key — one `AGE-SECRET-KEY-1…` line — **once**, and asks you to type its last 6 characters back to show it is saved. Only the public half is kept on the host, as `KENDO_BACKUP_RECIPIENT` in `~/.config/kendo/backup.env`. That is the point: nothing on the host can read a backup back, so neither can anyone who breaks into it.

It also means **losing the key loses the backups.** Nobody can decrypt a backup without the key it was made under — not the project, not the host, not you. The live database is unaffected; what you lose is the ability to restore.

With no key set, backups are still written, unencrypted, with a warning on every run. No backup would be worse.

### Keeping the key

- **Keep it in two places**, e.g. the club's password manager plus a printed copy with the club records.
- **Save it with its start date**, e.g. "Kendo backup key (from 2026-10-06)". A backup's filename carries its date, so the date shows which key opens it after a change.
- **When a volunteer leaves**, the key is handed over, not lost. If they kept a copy, [change it](#lost-or-leaked-key).

## Restore

Destructive — stops writes, drops and recreates the database:

```bash
systemctl --user stop kendo-app
# Second argument is optional; pass the uploads tarball with the same timestamp
# to restore logos and backgrounds alongside the database.
~/.local/bin/kendo-restore.sh \
  ~/backups/kendo-YYYYmmdd-HHMMSS.dump.age \
  ~/backups/kendo-uploads-YYYYmmdd-HHMMSS.tar.age
systemctl --user restart kendo-migrate kendo-app
# Stopping kendo-app stopped Traefik too, which needs it (Requires=); restarting
# the app does not bring it back, so start it (#628).
systemctl --user start kendo-traefik
```

On the Compose stack, from the install directory. Its database container and uploads volume are project-scoped, so name them (a failed `setup.sh upgrade` prints this command with them filled in):

```bash
podman-compose stop app
KENDO_DB_CONTAINER=$(podman ps -a --format '{{.Names}}' \
    --filter label=com.docker.compose.project=kendodojo \
    --filter label=com.docker.compose.service=db) \
KENDO_UPLOADS_VOLUME=kendodojo_static_uploads \
  bash deploy/bin/kendo-restore.sh \
  ~/backups/kendo-YYYYmmdd-HHMMSS.dump.age \
  ~/backups/kendo-uploads-YYYYmmdd-HHMMSS.tar.age
podman-compose up -d --force-recreate
```

Both end by re-running migrate, as the restore prints when it finishes: the app's database user has no grants until it does (#481).

Plaintext backups (`.dump`, `.tar`, from before a key was set) restore with the same command.

For an encrypted backup it asks for the key at a hidden prompt: paste the whole `AGE-SECRET-KEY-1…` line. This works inside `sudo machinectl shell kendo@ /bin/bash`. The key is never written to disk, and neither is anything it decrypts — it streams straight into `pg_restore` and the uploads volume.

The key is checked against every file before anything is changed, so a wrong key leaves the database untouched:

- *"This backup was encrypted with a different key"* — keys were changed since. Use the one that was active on the date in the filename.
- *"That is not a valid backup key"* — the paste is incomplete. Paste the whole line, exactly as saved.

## Restore drill

Check that the backups you have actually open, without touching the server. On any machine with `age` and the PostgreSQL client tools, with the key saved to `key.txt`:

```bash
age -d -i key.txt kendo-<stamp>.dump.age | pg_restore --list | head
age -d -i key.txt kendo-uploads-<stamp>.tar.age | tar -t | head
rm key.txt
```

A table of contents and a list of files mean the backup is good. Nothing decrypted is written to disk; only `key.txt` is, so delete it afterwards.

Run it now and then — monthly, say — against the newest **off-site** copy, not the one on the host. One drill shows that backups are still being made, that they reach the remote, and that the key still opens them. Nothing reminds you; put it in the club calendar.

## Lost or leaked key

A new key can be set at any time with `./setup.sh backup-key --quadlet`. It runs the same save-and-confirm as install, takes a backup under the new key at once, then lists the older backups and offers to delete them.

Only backups made from then on use the new key. Older ones still open only with the old key — that cannot be worked around, or an attacker could do it too.

- **Lost** (nobody has the key any more): set a new key. The older backups can no longer be opened; delete them, or let them age out — 14 runs on the host, and `KENDO_BACKUP_REMOTE_KEEP_DAYS` off-site.
- **Leaked** (someone else may have it — a volunteer left on bad terms, a printed copy went missing, the password manager was breached): set a new key **and** delete the older backups everywhere. Off-site, that includes emptying the provider's trash or recycle bin, or the files stay readable there for another 30 days or so.

## Off-site copies (optional)

A backup on the host does not survive losing the host — an old PC, a Raspberry Pi, a cheap VPS. Each run can copy its encrypted files to storage the club already has, with [rclone](https://rclone.org/). Add to `~/.config/kendo/backup.env` — an rclone remote, then a folder, and optionally how long to keep copies:

```bash
KENDO_BACKUP_REMOTE=gdrive:kendo-backups
KENDO_BACKUP_REMOTE_KEEP_DAYS=90
```

- Encrypted (`.age`) files from the last 7 days that the remote does not have yet are copied, so a copy that failed one night goes up with the next. **Plaintext never leaves the host:** with no backup key, the copy is skipped and the log says why, and plaintext backups from before the key are never copied.
- `KENDO_BACKUP_REMOTE_KEEP_DAYS` deletes `kendo-*.age` files older than that many days, in that folder only. About 90 is a good value: it also limits how long an erased Member's data survives in backups. Leave it unset if the credential cannot delete (see below).
- If the copy fails, the local backup is kept, the run shows as failed in `systemctl --user status kendo-backup` (as `kendo`), and `./setup.sh upgrade` carries on regardless. The reason is in the unit's log, read from your admin account: `sudo journalctl _UID=$(id -u kendo) _SYSTEMD_USER_UNIT=kendo-backup.service --no-pager` ([Deployment § Logs](../deployment.md#9-logs)).
- Each rclone call is stopped after an hour, so a stalled upload cannot block the next night's backup. On a slow link, raise it with `KENDO_BACKUP_REMOTE_TIMEOUT=2h` (or `30m`, `90s`).

rclone runs as `kendo`, with `kendo`'s own config. Install it and add a remote from a `machinectl` shell:

```bash
sudo dnf install -y rclone   # or: sudo apt install -y rclone
sudo machinectl shell kendo@ /bin/bash
rclone config
```

The host has no browser, so the login is done on a laptop: answer `n` to *"Use auto config?"*, run the `rclone authorize …` command it prints on a laptop with rclone installed, and paste the token back. Details: [rclone remote setup](https://rclone.org/remote_setup/).

Then check it works after the next backup:

```bash
systemctl --user start kendo-backup.service
rclone lsf gdrive:kendo-backups
```

### Keep the credential's reach small

The rclone credential lives on the host. Whoever controls the host can do anything that credential can, so give it the backups and nothing else:

- **Google Drive:** `scope = drive.file` (below) — rclone sees only the files it created, so the club's other Drive files are out of reach.
- **OneDrive:** rclone has no setting that narrows it; the token reaches the whole OneDrive, including files shared with that account. Use a separate Microsoft account that holds only the backups.
- **B2 or S3-compatible storage:** a key limited to one bucket (and a name prefix), with no delete permission. Expire old copies with the bucket's lifecycle rule, and leave `KENDO_BACKUP_REMOTE_KEEP_DAYS` unset.
- **Hetzner Storage Box:** a sub-account limited to one directory.
- **SFTP to a NAS:** a dedicated user confined to one folder.
- **Any provider:** an account that holds nothing but the backups. Keep its login in the club password manager, next to the backup key.

### What the trash protects, and what it doesn't

Google Drive and OneDrive cannot issue a credential without delete rights. Deletes made the normal way — including `KENDO_BACKUP_REMOTE_KEEP_DAYS` expiry — go to the trash or recycle bin, which keeps them for about 30 days. That catches mistakes. It does **not** stop someone who has taken over the host: the same credential can delete permanently, skipping the trash.

So on Drive and OneDrive, someone who has taken over the host can delete the off-site copies along with the host's own. For a club that is usually an acceptable risk — the backups are encrypted, so a breach cannot read them, only destroy them. If it is not acceptable for yours, use a credential without delete rights (B2 above, or storage with object lock or snapshots), or have another machine pull the backups instead.

Expired copies also sit in the trash for those 30 days, so an erased Member's data can outlive `KENDO_BACKUP_REMOTE_KEEP_DAYS` by that long.

### Google Drive

In `rclone config`: storage type `drive`, and at the scope question choose `drive.file`. Name the remote `gdrive`, then:

```bash
KENDO_BACKUP_REMOTE=gdrive:kendo-backups
KENDO_BACKUP_REMOTE_KEEP_DAYS=90
```

Log in with `rclone authorize "drive"` on the laptop. If transfers are slow or fail with rate-limit errors, rclone's shared client ID is busy; [rclone's Drive page](https://rclone.org/drive/) shows how to make your own.

### OneDrive

Ideally under a Microsoft account used only for the backups (see above). In `rclone config`: storage type `onedrive`, name the remote `onedrive`, then:

```bash
KENDO_BACKUP_REMOTE=onedrive:kendo-backups
KENDO_BACKUP_REMOTE_KEEP_DAYS=90
```

Log in with `rclone authorize "onedrive"` on the laptop. Personal versus business accounts, scopes, and Microsoft 365 admin approval are covered on [rclone's OneDrive page](https://rclone.org/onedrive/).

### Other storage

Anything rclone supports works — the files are already encrypted, so the storage need not be trusted with member data. See [rclone's provider list](https://rclone.org/overview/).

- **Backblaze B2:** a bucket-scoped key without delete permission, plus a lifecycle rule. The strongest option here.
- **Cloudflare R2:** S3-compatible, with no charge for downloading a backup to restore.
- **Hetzner Storage Box:** SFTP, with a sub-account per directory and its own snapshots.
- **SFTP to a NAS:** best with the NAS's snapshots turned on.
- **Avoid Wasabi:** it bills a 1 TB minimum and charges each object for 90 days, however briefly it is kept.

### Pulling instead of pushing

A NAS or another always-on machine can pull the encrypted backups from `~/backups` on its own schedule, instead of the host pushing them. The host then holds no credential that can reach the copies. How to set that up depends on the machine and is not covered here. `./setup.sh check` will still warn that no off-site copy is configured, because the host cannot see the pull.

## The disk itself

Encrypted backups do not protect the live database or the uploads volume on the host's disk. Full-disk encryption on the host (LUKS, or your cloud provider's encrypted volumes) covers a stolen disk or a decommissioned drive: see [Encrypt the disk](../deployment.md#10-encrypt-the-disk).
