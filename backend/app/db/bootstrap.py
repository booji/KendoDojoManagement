"""Bring a database from whatever state it's in up to the current schema.

Run before the app starts, as its own unit rather than a step inside the app
container: the `migrate` service in docker-compose.yml, kendo-migrate.service
under Quadlet, and run_tests.sh in the test harness. The app process itself
no longer runs this (#391), so a failed migration fails as itself instead of
as an app that crashed on boot.

Schema creation flows exclusively through the Alembic migration chain now
that the chain has a baseline migration (`000000000000_baseline_schema.py`)
as its revision zero: `alembic upgrade head` replays cleanly from a genuinely
empty database, so there is no need to special-case "fresh" databases with
`Base.metadata.create_all` + `alembic stamp head` — that branch (and the
drift risk of maintaining two schema sources) is gone. `prepare_database`
waits for the database to become reachable, then runs `alembic upgrade head`
unconditionally, whatever state the database is already in (empty,
mid-migration, or already at head).

It then creates and maintains the app's own database user (ADR-0007, #453).
Migrations run as the superuser in MIGRATION_DATABASE_URL; the app connects as
the user named in DATABASE_URL, which can only read and write rows. Every run
creates that user if missing, sets its password from DATABASE_URL and
re-applies its grants, so an existing volume is covered, drift is repaired,
and rotating the password is changing the secret and restarting.

Assumes one process bootstraps a given database at a time — true of the
single migration unit this project ships. Running two of them concurrently
against the same empty volume would need an advisory lock here first.
"""

import asyncio
import logging
import os

import asyncpg
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import DATABASE_URL, MIGRATION_DATABASE_URL
from app.db.scratch import asyncpg_dsn, url_parts, validate_identifier

_log = logging.getLogger(__name__)

_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _redact(exc: Exception, database_url: str) -> str:
    """Describe `exc` with the database password masked out.

    Connection errors are logged verbatim on the retry path; drivers are not
    contractually bound to keep the DSN out of their message text, so strip
    the password before it can reach a log aggregator.
    """
    text = f"{type(exc).__name__}: {exc}"
    password = make_url(database_url).password
    return text.replace(password, "***") if password else text


def _alembic_config(database_url: str):
    from alembic.config import Config

    # Deliberately built without alembic.ini: alembic/env.py calls
    # `fileConfig(config.config_file_name)` whenever one is set, and
    # fileConfig disables every logger it doesn't know about. In-process that
    # silently decapitates the app's own logging (the security logger in
    # particular) for the rest of the process. Leaving config_file_name as
    # None skips that call; the only settings this module needs from the ini
    # are set explicitly below.
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "alembic"))
    cfg.set_main_option("version_path_separator", "os")
    # alembic/env.py migrates the URL set here and nothing in the environment:
    # in kendo-migrate DATABASE_URL(_FILE) is the app user's login, and the
    # migration must run as the superuser it is handed (ADR-0007).
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _run_alembic_upgrade(database_url: str) -> None:
    """Run `alembic upgrade head` against `database_url`. Blocking — call via a
    thread: alembic's env.py drives its own event loop (`asyncio.run(...)`),
    which cannot be nested inside the event loop this module's async callers
    run on.
    """
    from alembic import command

    command.upgrade(_alembic_config(database_url), "head")


async def _upgrade_head(database_url: str) -> None:
    """Run all pending alembic migrations up to head."""
    await asyncio.to_thread(_run_alembic_upgrade, database_url)


async def _wait_for_connection(
    engine: AsyncEngine, max_attempts: int, initial_delay: float, database_url: str
) -> None:
    """Retry a bare connection with exponential backoff until the DB is reachable."""
    attempt = 0
    delay = initial_delay
    while True:
        try:
            async with engine.connect():
                return
        except Exception as exc:
            attempt += 1
            if attempt >= max_attempts:
                _log.error(
                    "Database not reachable after %d attempts: %s",
                    attempt,
                    _redact(exc, database_url),
                )
                raise
            _log.warning(
                "Database not ready (attempt %d/%d): %s — retrying in %.2fs",
                attempt,
                max_attempts,
                _redact(exc, database_url),
                delay,
            )
            await asyncio.sleep(delay)
            delay *= 2


def _app_login(migration_url: str, app_url: str) -> tuple[str, str]:
    """The app user's (name, password) from `app_url`, refused unless it is a
    separate, safely named user with a password.

    The name is interpolated into DDL — roles, like databases, cannot be bind
    parameters — so it goes through scratch's identifier check, the one
    security boundary for that.
    """
    app = make_url(app_url)
    validate_identifier(app.username or "")
    if app.username == make_url(migration_url).username:
        raise RuntimeError(
            f"DATABASE_URL and MIGRATION_DATABASE_URL both log in as "
            f"{app.username!r}. DATABASE_URL must name the restricted app user "
            "and MIGRATION_DATABASE_URL the superuser (ADR-0007)."
        )
    if not app.password:
        raise RuntimeError(
            f"DATABASE_URL has no password for the app user {app.username!r}."
        )
    return app.username, app.password


async def _ensure_app_user(migration_url: str, user: str, password: str) -> None:
    """Create `user` if missing, then reset its attributes, password and grants.

    Row access only: no TRUNCATE, TRIGGER, REFERENCES or CREATE, and
    alembic_version is read-only so a compromised app cannot fake the schema
    version. Default privileges cover tables later migrations create as the
    migration user, so a new migration needs no grants of its own. Every
    grant is revoked and re-granted inside one transaction, so drift is
    repaired without the app ever seeing a gap.
    """
    base_url, db_name = url_parts(migration_url)
    conn = await asyncpg.connect(asyncpg_dsn(base_url, db_name))
    try:
        migrator = await conn.fetchval("SELECT current_user")
        for identifier in (user, migrator, db_name):
            validate_identifier(identifier)
        # The ALTER below would demote it: a DATABASE_URL naming another
        # superuser is a misconfiguration, not drift to repair.
        if await conn.fetchval(
            "SELECT rolsuper FROM pg_roles WHERE rolname = $1", user
        ):
            raise RuntimeError(
                f"DATABASE_URL names {user!r}, an existing superuser. It must "
                "name the restricted app user (ADR-0007); refusing to demote it."
            )
        # Two test runs sharing a server can both see the role missing; the
        # loser's CREATE is a no-op, and the ALTER below does the real work.
        try:
            await conn.execute(f'CREATE ROLE "{user}"')
        except asyncpg.DuplicateObjectError:
            pass
        # PASSWORD takes a literal, never a parameter: quote it server-side.
        literal = await conn.fetchval("SELECT quote_literal($1)", password)
        await conn.execute(
            f'ALTER ROLE "{user}" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
            f"NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {literal}"
        )
        rows = "SELECT, INSERT, UPDATE, DELETE"
        defaults = f'ALTER DEFAULT PRIVILEGES FOR ROLE "{migrator}" IN SCHEMA public'
        async with conn.transaction():
            for statement in (
                f'REVOKE ALL ON DATABASE "{db_name}" FROM "{user}"',
                f'GRANT CONNECT ON DATABASE "{db_name}" TO "{user}"',
                f'REVOKE ALL ON SCHEMA public FROM "{user}"',
                f'GRANT USAGE ON SCHEMA public TO "{user}"',
                f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{user}"',
                f'GRANT {rows} ON ALL TABLES IN SCHEMA public TO "{user}"',
                f'REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM "{user}"',
                f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM "{user}"',
                f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{user}"',
                f'{defaults} REVOKE ALL ON TABLES FROM "{user}"',
                f'{defaults} GRANT {rows} ON TABLES TO "{user}"',
                f'{defaults} REVOKE ALL ON SEQUENCES FROM "{user}"',
                f'{defaults} GRANT USAGE, SELECT ON SEQUENCES TO "{user}"',
            ):
                await conn.execute(statement)
    finally:
        await conn.close()


async def prepare_database(
    migration_url: str | None = None,
    app_url: str | None = None,
    *,
    max_attempts: int = 10,
    initial_delay: float = 1.0,
) -> None:
    """Bring the database up to head, then (re)provision the app user.

    `migration_url` (default MIGRATION_DATABASE_URL) is the superuser login
    that migrates; `app_url` (default DATABASE_URL) names the app user to
    maintain. Waits for the database to be reachable, then runs `alembic
    upgrade head` unconditionally — the same code path whether the target
    started empty or already had a schema.
    """
    migration_url = migration_url or MIGRATION_DATABASE_URL
    app_url = app_url or DATABASE_URL
    if not migration_url or not app_url:
        raise RuntimeError(
            "The migration step needs MIGRATION_DATABASE_URL (the superuser) "
            "and DATABASE_URL (the app user) both set (ADR-0007)."
        )
    user, password = _app_login(migration_url, app_url)
    engine = create_async_engine(migration_url)
    try:
        await _wait_for_connection(engine, max_attempts, initial_delay, migration_url)
    finally:
        await engine.dispose()
    await _upgrade_head(migration_url)
    await _ensure_app_user(migration_url, user, password)


if __name__ == "__main__":
    asyncio.run(prepare_database())
