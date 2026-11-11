# Day-2 operations

| Task | Command (as `kendo` via `machinectl shell kendo@ /bin/bash`) |
|------|----|
| Status | `systemctl --user status kendo-app --no-pager` |
| Logs | `podman logs -f kendo-app` |
| Restart app | `systemctl --user restart kendo-app` |
| **Upgrade** — the full procedure is [Upgrading](../install/upgrading.md#hardened-deployment-quadlet) | `podman pull ghcr.io/booji/kendodojomanagement:0.1 && systemctl --user restart kendo-migrate kendo-app` |
| Stop all | `systemctl --user stop kendo-ip-retention.timer kendo-traefik kendo-app kendo-migrate kendo-db` — the timer first, or its daily run starts `kendo-db` again |
| Back up now | `systemctl --user start kendo-backup.service` |
| New backup key — see [Backups](../install/backups.md#lost-or-leaked-key) | `./setup.sh backup-key --quadlet` (from the deployment bundle) |
| Break-glass recovery | `podman exec kendo-app python -m app.cli create-recovery-token <email>` |

> The pin is the `Image=` line in the three app-image Quadlet units (`kendo-app`,
> `kendo-migrate`, `kendo-ip-retention`), and the documented
> value is the **Release line** tag `:0.1` — fixes and features, but no
> Breaking change. Moving to `:0.2` is a deliberate edit made after reading its
> section in [Upgrading](../install/upgrading.md). Building from source still works
> (`podman build -t localhost/kendodojo:latest .`); point `Image=` at it.
