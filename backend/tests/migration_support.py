"""Scratch-database helpers for tests that migrate their own database.

Each test gets a throwaway database (the `scratch_db` fixture in conftest.py;
see test_migrations.py for why not the shared one), drives alembic to a chosen
revision, and talks to it in raw SQL: what is under test is what the migration
and the database do, not what the app checks first.
"""

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.db.bootstrap import _alembic_config


def _upgrade_blocking(url: str, revision: str) -> None:
    cfg = _alembic_config(url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


async def upgrade(url: str, revision: str = "head") -> None:
    # env.py runs its own asyncio.run(), which cannot nest in the test's loop.
    await asyncio.to_thread(_upgrade_blocking, url, revision)


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
