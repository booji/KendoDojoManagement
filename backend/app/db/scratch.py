"""Create, drop, and sweep throwaway PostgreSQL databases (issue #329).

The single home for "create/drop/sweep a scratch database" — previously
duplicated three times: `run_tests.sh`'s two inline python3/asyncpg
heredocs (per-run database create/drop) and `test_migrations.py`'s
`_create_scratch_database` / `_drop_scratch_database` pair (per-test
migration scratch databases). All three now call through here.

Identifier validation (`is_safe_identifier` / `validate_identifier`) is a
security boundary, not mere formatting: database names are interpolated
directly into DDL (`CREATE DATABASE "..."`, `DROP DATABASE IF EXISTS
"..."`) because PostgreSQL has no parameterised way to pass an identifier,
only values. It lives in exactly this one place — every call site in this
codebase that builds such DDL must route through here rather than
re-deriving its own regex.

`select_sweepable` is the pure core of the sweep: given `(datname,
connection_count)` rows as would come back from a `pg_stat_activity` join,
it decides which are safe to drop with no database connection at all. That
split is what makes the sweep's safety rules unit-testable without a live
server, and it is deliberately kept as a separate function so
`sweep_orphaned_databases` stays a thin, mechanical wrapper: query, filter,
drop.

Also exposes a CLI (`python -m app.db.scratch create|drop|sweep`) used by
`run_tests.sh`. The DSN is read from the environment, never argv:
`/proc/<pid>/cmdline` is world-readable within a container's PID namespace,
and the DSN carries the database password.
"""

import argparse
import asyncio
import os
import re

import asyncpg

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


def is_safe_identifier(name: str) -> bool:
    """True if `name` is safe to interpolate into DDL as a bare identifier.

    Restricted to alphanumerics and underscore — no quotes, whitespace,
    dots, hyphens, or SQL comment sequences. Deliberately conservative: this
    is the only thing standing between an untrusted-ish database name and a
    DDL statement that cannot be parameterised.
    """
    return bool(name) and bool(_SAFE_IDENTIFIER_RE.fullmatch(name))


def validate_identifier(name: str) -> None:
    """Raise ValueError unless `name` is safe (see `is_safe_identifier`)."""
    if not is_safe_identifier(name):
        raise ValueError(f"refusing unsafe database identifier: {name!r}")


def url_parts(database_url: str) -> tuple[str, str]:
    """Split a `postgresql[+asyncpg]://...` URL into (base_url, db_name).

    `base_url` has no trailing slash or database name; `db_name` has any
    query string stripped.
    """
    base, _, db_and_query = database_url.rpartition("/")
    db_name = db_and_query.split("?", 1)[0]
    return base, db_name


def asyncpg_dsn(base_url: str, db_name: str) -> str:
    """Build a plain asyncpg DSN (no `+asyncpg` driver suffix) for maintenance ops."""
    plain = base_url.replace("postgresql+asyncpg://", "postgresql://")
    return f"{plain}/{db_name}"


async def create_database(base_url: str, db_name: str) -> str:
    """Create `db_name` on the server named by `base_url`.

    Returns the full SQLAlchemy URL (`base_url/db_name`).
    """
    validate_identifier(db_name)
    conn = await asyncpg.connect(asyncpg_dsn(base_url, "postgres"))
    try:
        # CREATE DATABASE cannot run inside a transaction block; asyncpg does
        # not implicitly wrap a bare execute() in one, so this is safe as-is.
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()
    return f"{base_url}/{db_name}"


async def drop_database(base_url: str, db_name: str) -> None:
    """Drop `db_name`, forcibly terminating any active backends first.

    Sequence: disallow new connections, terminate whatever is already
    connected, then drop. Without this, a database with even one lingering
    connection fails to drop with "database is being accessed by other
    users".
    """
    validate_identifier(db_name)
    conn = await asyncpg.connect(asyncpg_dsn(base_url, "postgres"))
    try:
        await conn.execute(f'ALTER DATABASE "{db_name}" WITH ALLOW_CONNECTIONS false')
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            db_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        await conn.close()


def select_sweepable(
    rows: list[tuple[str, int]], prefix: str = "kendo_test_"
) -> list[str]:
    """Pure filter: which `(datname, connection_count)` rows are safe to drop.

    Safe means: the name starts with `prefix`, and it currently has zero
    live connections. No I/O here — this is what makes the sweep's safety
    rules testable without a live server; `sweep_orphaned_databases` is a
    thin wrapper around this function.
    """
    return [name for name, count in rows if name.startswith(prefix) and count == 0]


async def sweep_orphaned_databases(
    base_url: str, prefix: str = "kendo_test_"
) -> list[str]:
    """Drop every database matching `prefix` that currently has no connections.

    Queries `pg_database` joined against `pg_stat_activity` for a live
    connection count per database, hands the rows to `select_sweepable`,
    then drops whatever it selects. Returns the names actually dropped.
    """
    conn = await asyncpg.connect(asyncpg_dsn(base_url, "postgres"))
    try:
        rows = await conn.fetch(
            "SELECT d.datname, COUNT(a.pid) AS connections "
            "FROM pg_database d "
            "LEFT JOIN pg_stat_activity a ON a.datname = d.datname "
            "WHERE d.datname LIKE $1 "
            "GROUP BY d.datname",
            f"{prefix}%",
        )
    finally:
        await conn.close()

    candidates = select_sweepable(
        [(row["datname"], row["connections"]) for row in rows], prefix=prefix
    )
    dropped: list[str] = []
    for db_name in candidates:
        await drop_database(base_url, db_name)
        dropped.append(db_name)
    return dropped


def _base_url_from_env() -> str:
    """Read the base URL (no database name) from the environment.

    Accepts either SCRATCH_DB_BASE_URL directly, or DATABASE_URL to split
    via `url_parts`. Never read from argv — see module docstring.
    """
    base_url = os.environ.get("SCRATCH_DB_BASE_URL")
    if base_url:
        return base_url
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "SCRATCH_DB_BASE_URL or DATABASE_URL must be set in the environment"
        )
    base_url, _ = url_parts(database_url)
    return base_url


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `python -m app.db.scratch create|drop|sweep`.

    The database name for create/drop comes from SCRATCH_DB_NAME (env), and
    the server to talk to from SCRATCH_DB_BASE_URL or DATABASE_URL (env) —
    never from argv, which is world-readable via /proc/<pid>/cmdline within
    a container's PID namespace and would otherwise leak the DSN password.
    """
    parser = argparse.ArgumentParser(prog="python -m app.db.scratch")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("create")
    subparsers.add_parser("drop")
    sweep_parser = subparsers.add_parser("sweep")
    sweep_parser.add_argument("--prefix", default="kendo_test_")

    args = parser.parse_args(argv)
    base_url = _base_url_from_env()

    if args.command == "create":
        db_name = os.environ.get("SCRATCH_DB_NAME")
        if not db_name:
            print("SCRATCH_DB_NAME must be set in the environment", flush=True)
            return 1
        try:
            asyncio.run(create_database(base_url, db_name))
        except ValueError as exc:
            print(str(exc), flush=True)
            return 1
        # Print the bare name, never the URL create_database returns: that URL
        # carries the DSN password, and this command's stdout lands in the test
        # container's log. Same reasoning as keeping the DSN out of argv.
        print(db_name, flush=True)
        return 0

    if args.command == "drop":
        db_name = os.environ.get("SCRATCH_DB_NAME")
        if not db_name:
            print("SCRATCH_DB_NAME must be set in the environment", flush=True)
            return 1
        try:
            asyncio.run(drop_database(base_url, db_name))
        except ValueError as exc:
            print(str(exc), flush=True)
            return 1
        return 0

    if args.command == "sweep":
        dropped = asyncio.run(sweep_orphaned_databases(base_url, prefix=args.prefix))
        for name in dropped:
            print(name, flush=True)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
