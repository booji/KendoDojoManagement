"""What docker-compose.yml, deploy/quadlet and setup.sh must agree on, shared
by the tests that check each of them. The deploy files keep their own lines."""

from pathlib import Path

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

# Where an operator pins a Version (#604): the Quadlet units that run the
# Release image, and Compose's .env key. Editing these is how an rc is
# rehearsed and how an upgrade is rolled back; nothing else names the image.
IMAGE_PIN_UNITS = [
    "kendo-app.container",
    "kendo-migrate.container",
    "kendo-ip-retention.container",
]
COMPOSE_IMAGE_PIN = "KENDO_IMAGE"

# The deployment files an operator owns once installed (#604). No upgrade
# step overwrites one: a pull request that changes one writes an Operator
# action for the release notes. deploy/bin is here too: the backup timer runs
# an installed copy, so a changed script reaches no host by itself. So is
# setup.sh: it runs from the bundle the operator extracted, and a change to
# what it writes reaches a host only when the operator re-runs it.
DEPLOYMENT_FILES = [
    "deploy/quadlet",
    "deploy/systemd",
    "deploy/bin",
    "docker-compose.yml",
    "deploy/env",
    ".env.example",
    "deploy/traefik",
    "setup.sh",
]


# The env files a Compose service reads that setup.sh generates on the host,
# each from the shipped example it is written from (#603). A checkout has only
# the example, so the file tests read it in the generated file's place.
GENERATED_ENV_FILES = {"kendo-app.env": "deploy/env/kendo-app.env.example"}


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def container_env(
    service: dict, root: Path, stand_ins: dict[str, str] | None = None
) -> dict[str, str]:
    """What a Compose service's container sees: its env_file entries, read
    from root (or the stand-in for a generated one), overridden by its
    environment: block. The env_file half is what #483 slipped through."""
    env_files = service.get("env_file", [])
    if isinstance(env_files, str):
        env_files = [env_files]
    merged: dict[str, str] = {}
    for entry in env_files:
        path = entry["path"] if isinstance(entry, dict) else entry
        merged |= read_env_file(root / (stand_ins or {}).get(path, path))
    env = service.get("environment", {})
    if isinstance(env, list):
        return merged | dict(entry.split("=", 1) for entry in env)
    return merged | {k: str(v) for k, v in env.items()}
