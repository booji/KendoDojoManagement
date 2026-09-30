# Make targets

| Target | What it does |
|--------|-------------|
| `make` | List the targets (starts nothing) |
| `make dev` | Start the hot-reload dev stack |
| `make test` | Start the test watcher (re-runs pytest on every save) |
| `make screenshots` | Regenerate the README / docs sessions screenshots (`docs/assets`, desktop and mobile, light and dark) from a made-up dojo — rerun after a UI change to the calendar |
| `make build` | Build the production image as `localhost/kendodojo:latest` (releases run the published image — see [ADR-0004](../adr/0004-published-images-pinned-by-major-tag.md)) |
| `make down` | Stop the stacks this checkout starts — dev and test |
| `make down-selfhost` | Stop the quick self-host stack — **takes the dojo offline** |
| `make certs` | Issue the `dojo.localhost` dev TLS certificate if it is missing or untrusted (run for you by `make dev`) |
| `make certs-force` | Reissue the dev TLS certificate unconditionally |
| `make logs` | Tail dev service logs |
| `make migrate` | Run `alembic upgrade head` in the running dev container |
| `make help` | List all targets |

The Makefile auto-detects `podman-compose` vs `docker compose`, so the targets run under either. That detection is kept because it costs nothing, not because Docker is tested — see [Container runtime](../index.md#container-runtime).

`make down` deliberately leaves the quick self-host alone: on a machine that is
actually serving a dojo, stopping it must be a deliberate act, so it has its own
target. The same reasoning already governs `make clean` refusing to remove the
production database volume.

`make dev` generates a per-machine `dojo.localhost` certificate under
`deploy/certs/` (gitignored) if one is missing, self-signed while mkcert is
available, or no longer covering the dev host. The full step — generate, trust,
verify, reissue, and the failure modes — is [The dev TLS
certificate](dev-stack.md#the-dev-tls-certificate).
