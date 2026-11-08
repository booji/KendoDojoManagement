"""What docker-compose.yml, deploy/quadlet and setup.sh must agree on, shared
by the tests that check each of them. The deploy files keep their own lines."""

# The Quadlet unit that runs each Compose service.
QUADLET_UNITS = {
    "app": "kendo-app.container",
    "migrate": "kendo-migrate.container",
    "proxy": "kendo-traefik.container",
}

# The secrets each service reads from a mounted file (#462, read_secret in
# app/config.py).
SECRETS = {
    "app": ["DATABASE_URL", "JWT_SECRET", "SETUP_TOKEN"],
    "migrate": ["MIGRATION_DATABASE_URL", "DATABASE_URL"],
}
ALL_SECRETS = sorted({name for names in SECRETS.values() for name in names})

# The services hardened against a breach (#458), each with the capabilities it
# adds back after dropping all. Traefik binds 80/443 inside its own namespace;
# nothing else needs one. Postgres is out of scope: its entrypoint's user
# switch needs its own capability set.
CAPABILITIES_ADDED_BACK = {
    "app": [],
    "migrate": [],
    "proxy": ["NET_BIND_SERVICE"],
}

# The image tag every shipped file and operator page names: the pin of the
# current Release line (ADR-0004), 0.Y before 1.0 (ADR-0009). A new Release
# line changes it here, and the tests then name every file still on the old
# one. release.yml refuses to publish a tag whose pin the files do not name,
# so a line missed here and in a file alike cannot ship either.
PUBLISHED_IMAGE = "ghcr.io/booji/kendodojomanagement"
RELEASE_PIN = f"{PUBLISHED_IMAGE}:0.1"

# The only files that may set ALLOW_TEST_AUTH, which registers a route that
# signs anyone in as an admin with no credential (#590). Every other compose,
# Quadlet and env file in the repo ships to someone.
TEST_ONLY_FILES = (".env.test", "docker-compose.test.yml")
