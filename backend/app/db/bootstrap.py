"""Bring a database from whatever state it's in up to the current schema.

Run before the app starts (see the repo-root `entrypoint.sh`). Schema
creation flows exclusively through the Alembic migration chain now that the
chain has a baseline migration (`000000000000_baseline_schema.py`) as its
revision zero: `alembic upgrade head` replays cleanly from a genuinely empty
database, so there is no need to special-case "fresh" databases with
`Base.metadata.create_all` + `alembic stamp head` — that branch (and the
drift risk of maintaining two schema sources) is gone. `prepare_database`
now does one thing: wait for the database to become reachable, then run
`alembic upgrade head` unconditionally, whatever state the database is
already in (empty, mid-migration, or already at head).

Assumes one process bootstraps a given database at a time — true of the
single-app-container compose stack this project ships. Scaling the app
service to more than one replica racing against the same empty volume would
need an advisory lock here first.
"""

import asyncio
import logging
import os

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
    # duration of the command — see _upgrade_head.
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _run_alembic_upgrade(database_url: str) -> None:
    """Run `alembic upgrade head` against `database_url`. Blocking — call via a
    thread: alembic's env.py drives its own event loop (`asyncio.run(...)`),
    which cannot be nested inside the event loop this module's async callers
    run on.
    """
    from alembic import command

    cfg = _alembic_config(database_url)

    # env.py prefers the DATABASE_URL env var over alembic.ini, so pin it to
    # the target database for the duration of the call and restore it after.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


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


async def prepare_database(
    database_url: str | None = None,
    *,
    max_attempts: int = 10,
    initial_delay: float = 1.0,
) -> None:
    """Bring `database_url` (or the configured DATABASE_URL) up to head.

    Waits for the database to be reachable, then runs `alembic upgrade head`
    unconditionally — the same code path whether the target started empty
    or already had a schema.
    """
    url = database_url or DATABASE_URL
    engine = create_async_engine(url)
    try:
        await _wait_for_connection(engine, max_attempts, initial_delay, url)
    finally:
        await engine.dispose()
    await _upgrade_head(url)


if __name__ == "__main__":
    asyncio.run(prepare_database())
