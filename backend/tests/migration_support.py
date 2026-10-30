"""Scratch-database helpers for tests that migrate their own database.

Each test gets a throwaway database (the `scratch_db` fixture in conftest.py;
see test_migrations.py for why not the shared one), drives alembic to a chosen
revision, and talks to it in raw SQL: what is under test is what the migration
and the database do, not what the app checks first.
"""

import asyncio
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from alembic.config import Config
from app.db.bootstrap import _alembic_config

# Roles are cluster-wide, so tests that run app.db.bootstrap provision their
# own app user rather than `kendo_app`: re-running bootstrap with a different
# password for the role the e2e server logs in as would lock it out mid-run.
APP_USER = "kendo_app_bootstrap_test"
APP_PASSWORD = "bootstrap-test-password"


def app_url(url: str, user: str = APP_USER, password: str = APP_PASSWORD) -> str:
    """`url` with the app user's login in place of the superuser's."""
    return (
        make_url(url)
        .set(username=user, password=password)
        .render_as_string(hide_password=False)
    )


def _migrate_blocking(
    url: str, migrate: Callable[[Config, str], None], revision: str
) -> None:
    migrate(_alembic_config(url), revision)


async def upgrade(url: str, revision: str = "head") -> None:
    # env.py runs its own asyncio.run(), which cannot nest in the test's loop.
    await asyncio.to_thread(_migrate_blocking, url, command.upgrade, revision)


async def downgrade(url: str, revision: str) -> None:
    await asyncio.to_thread(_migrate_blocking, url, command.downgrade, revision)


async def sql(url: str, *statements: str) -> list:
    """Run statements in one transaction; return the last one's rows."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            rows: list = []
            for statement in statements:
                result = await conn.execute(text(statement))
                rows = list(result) if result.returns_rows else []
            return rows
    finally:
        await engine.dispose()
