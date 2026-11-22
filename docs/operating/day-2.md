# Day-2 operations

| Task | Command (as `kendo` via `machinectl shell kendo@ /bin/bash`) |
|------|----|
| Status | `systemctl --user status kendo-app --no-pager` |
| Logs | `podman logs -f kendo-app` |
| A unit's journal (why it failed) | From your **admin account**, not `kendo`, which cannot read the journal: `sudo journalctl _UID=$(id -u kendo) _SYSTEMD_USER_UNIT=kendo-app.service --no-pager`; swap in any unit. See [Deployment § Logs](../deployment.md#9-logs) |
| Restart app | `systemctl --user restart kendo-app` |
| **Upgrade** | Follow [Upgrading § Hardened deployment](../install/upgrading.md#hardened-deployment-quadlet): it backs up, pulls every image and refreshes the bundle's copies — a pull and restart alone is not a patch |
| Stop all | `systemctl --user stop kendo-ip-retention.timer kendo-backup.timer kendo-traefik kendo-app kendo-migrate kendo-db` — the timers first, or their next run starts `kendo-db` again |
| Back up now | `systemctl --user start kendo-backup.service` |
| New backup key — see [Backups](../install/backups.md#lost-or-leaked-key) | `./setup.sh backup-key --quadlet` (from the deployment bundle) |
| Break-glass recovery | `podman exec kendo-app python -m app.cli create-recovery-token <email>` |

> The pin is the `Image=` line in the three app-image Quadlet units (`kendo-app`,
> `kendo-migrate`, `kendo-ip-retention`), and the documented
> value is the **Release line** tag `:0.1` — fixes and features, but no
> Breaking change. Moving to `:0.2` is a deliberate edit made after reading its
> section in [Upgrading](../install/upgrading.md). Building from source still works
> (`podman build -t localhost/kendodojo:latest .`); point `Image=` at it.
