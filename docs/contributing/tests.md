# Running tests

```bash
make test
```

This mounts `./backend` into a container alongside an ephemeral PostgreSQL instance and re-runs the full suite on every file change. The database is destroyed on `make down`.

One-shot run inside the running container:
```bash
podman-compose -f docker-compose.test.yml exec test pytest -q
```

A one-shot run of the whole suite, with optional pytest flags:
```bash
podman-compose -f docker-compose.test.yml run --rm test
podman-compose -f docker-compose.test.yml run --rm -e PYTEST_ARGS=-x test
podman-compose -f docker-compose.test.yml run --rm \
  -e PYTEST_TARGET=tests/test_members.py test
```

Pass pytest flags through `PYTEST_ARGS`, not positionally after the service
name: `podman-compose` treats trailing arguments as the container command, so
`run --rm test -x` fails with ``crun: executable file `-x` not found in
$PATH``. Only real `docker compose` forwards them. Both variables interpolate
unquoted, so keep values free of `*`, `?` and `[]`.
