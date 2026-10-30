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
