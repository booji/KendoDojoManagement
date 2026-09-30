# Backups (as `kendo`)

Nightly backup to `~/backups`, keeping the newest 14 of each artefact, driven by a systemd user timer. Each run writes two files sharing one timestamp:

| File | Contents |
| --- | --- |
| `kendo-<stamp>.dump` | Postgres, `pg_dump` custom format |
| `kendo-uploads-<stamp>.tar` | the `kendo-app-uploads` volume — logos and login backgrounds |

Uploaded images live on a volume, not in the database, so the dump alone does not cover them.

```bash
cp deploy/systemd/kendo-backup.service ~/.config/systemd/user/
cp deploy/systemd/kendo-backup.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kendo-backup.timer

# Verify schedule + run once now
systemctl --user list-timers kendo-backup.timer --no-pager
systemctl --user start kendo-backup.service
ls -lh ~/backups
```

**Restore** (destructive — stops writes, drops/recreates the DB):

```bash
systemctl --user stop kendo-app
# Second argument is optional; pass the uploads tarball with the same timestamp
# to restore logos and backgrounds alongside the database.
~/.local/bin/kendo-restore.sh \
  ~/backups/kendo-YYYYmmdd-HHMMSS.dump \
  ~/backups/kendo-uploads-YYYYmmdd-HHMMSS.tar
systemctl --user start kendo-app
```

> **Copy backups off-box.** A dump on the same host does not survive host loss. Ship `~/backups` elsewhere (rsync/restic/object storage) — not implemented here.
