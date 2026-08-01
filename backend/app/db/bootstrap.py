"""Bring a database from whatever state it's in up to the current schema.

Run before the app starts (see the repo-root `entrypoint.sh`). Historically
`entrypoint.sh` ran `alembic upgrade head` unconditionally, but the alembic
chain has no baseline migration — it assumes `members`, `sessions`, `users`
etc. already exist. On a genuinely empty database (a fresh volume) that made
`alembic upgrade head` the very first migration to run, which fails because
the tables it ALTERs don't exist yet.

The fix: decide in Python, before touching alembic, whether this is a fresh
database or an existing one.

- Fresh (no tables at all): create the full schema via
  `Base.metadata.create_all`, then `alembic stamp head` — record that the
  schema is already current without replaying migration history against it.
- Anything else (alembic_version present, or tables exist without one —
  e.g. a legacy pre-alembic deploy): run `alembic upgrade head` only. Never
  stamp on this path — that would silently skip real migrations.

Assumes one process bootstraps a given database at a time — true of the
single-app-container compose stack this project ships. The detect-then-act
sequence is not guarded by a lock, so two instances racing against the same
empty volume could both decide the database is fresh. Scaling the app service
to more than one replica would need an advisory lock here first.
"""

import asyncio
import logging
import os

from sqlalchemy import inspect
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import DATABASE_URL

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


async def _is_fresh(engine: AsyncEngine) -> bool:
    """True when the database has no tables at all.

    Inspects the connection's default search_path (`public` in every
    supported deployment). Tables parked in a non-default schema are not
    counted, so a database holding only those reads as fresh.
    """
    async with engine.connect() as conn:
        table_names = await conn.run_sync(lambda c: inspect(c).get_table_names())
    return len(table_names) == 0


async def _create_schema(engine: AsyncEngine) -> None:
    """Create every ORM-mapped table. Only safe to call on a fresh database."""
    # Import all model modules so their tables register on Base.metadata
    # before create_all runs — mirrors the imports in app.main.
    import app.attendance.db_models  # noqa: F401
    import app.auth.db_models  # noqa: F401
    import app.federations.db_models  # noqa: F401
    import app.grades.db_models  # noqa: F401
    import app.member_federations.db_models  # noqa: F401
    import app.members.db_models  # noqa: F401
    import app.sessions.db_models  # noqa: F401
    import app.settings.models  # noqa: F401
    from app.db.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
    # alembic/env.py reads the target URL from the DATABASE_URL env var
    # (falling back to alembic.ini's placeholder otherwise), so the caller
    # is responsible for having that env var point at `database_url` for the
    # duration of the command — see _run_alembic_command.
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _run_alembic_command(database_url: str, action: str) -> None:
    """Run an alembic command against `database_url`. Blocking — call via a thread.

    alembic's env.py drives its own event loop (`asyncio.run(...)`), which
    cannot be nested inside the event loop this module's async callers run
    on, so this must execute off the event loop thread (see _stamp_head /
    _upgrade_head).
    """
    from alembic import command

    cfg = _alembic_config(database_url)

    # env.py prefers the DATABASE_URL env var over alembic.ini, so pin it to
    # the target database for the duration of the call and restore it after.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        if action == "upgrade":
            command.upgrade(cfg, "head")
        elif action == "stamp":
            command.stamp(cfg, "head")
        else:  # pragma: no cover - internal misuse only
            raise ValueError(f"unknown alembic action: {action}")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


async def _stamp_head(database_url: str) -> None:
    """Record the current alembic head as applied, without running migrations."""
    await asyncio.to_thread(_run_alembic_command, database_url, "stamp")


async def _upgrade_head(database_url: str) -> None:
    """Run all pending alembic migrations up to head."""
    await asyncio.to_thread(_run_alembic_command, database_url, "upgrade")


async def _wait_for_connection(
    engine: AsyncEngine, max_attempts: int, initial_delay: float, database_url: str
) -> bool:
    """Retry `_is_fresh` with exponential backoff until the DB is reachable."""
    attempt = 0
    delay = initial_delay
    while True:
        try:
            return await _is_fresh(engine)
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


async def prepare_database(
    database_url: str | None = None,
    *,
    max_attempts: int = 10,
    initial_delay: float = 1.0,
) -> None:
    """Bring `database_url` (or the configured DATABASE_URL) up to head.

    Fresh database (no tables at all): create the schema directly and stamp
    head. Any other state (already at head, mid-migration, or a legacy
    pre-alembic schema with tables but no alembic_version): run
    `alembic upgrade head` only.
    """
    url = database_url or DATABASE_URL
    engine = create_async_engine(url)
    try:
        fresh = await _wait_for_connection(engine, max_attempts, initial_delay, url)
        if fresh:
            _log.info("Fresh database detected — creating schema and stamping head")
            await _create_schema(engine)
            await _stamp_head(url)
        else:
            _log.info("Existing database detected — running alembic upgrade head")
            await _upgrade_head(url)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(prepare_database())
