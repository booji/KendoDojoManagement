"""Failing tests for issue #153 — async CLI rewrite for create-recovery-token.

The current CLI uses a sync _get_engine() that strips '+asyncpg', leaving a bare
'postgresql://' URL which SQLAlchemy routes to psycopg2 — not installed.

Fix direction: rewrite CLI to be async, drop _get_engine(), use an async
SQLAlchemy session created from DATABASE_URL directly.

Acceptance criteria:
  AC1. create-recovery-token succeeds with sqlite+aiosqlite:// URL — no psycopg2
  AC2. _get_engine() sync helper is gone from cli.py
  AC3. CLI uses asyncio.run wrapping async commands
  AC4. No new packages added (aiosqlite already in dev deps)
  AC5. Works with aiosqlite URLs (dev/test compat)
  AC6. Exits code 1 + error when user not found
  AC7. Exits code 1 + error when DATABASE_URL not set
  AC8. create_engine / psycopg2 are never imported or called in the CLI path
"""

from __future__ import annotations

import os
import tempfile
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app.auth.db_models import AdminRecoveryToken, User
from app.cli import app as cli_app
from app.db.base import Base

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sqlite_async_url(path: str) -> str:
    return f"sqlite+aiosqlite:///{path}"


def _seed_user_sync(db_path: str, email: str) -> str:
    """Seed a user row synchronously so the CLI can find it."""
    from sqlalchemy import create_engine as _ce

    user_id = str(uuid.uuid4())
    engine = _ce(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            User(
                id=user_id,
                email=email,
                role="admin",
                is_active=True,
            )
        )
        session.commit()
    engine.dispose()
    return user_id


# ---------------------------------------------------------------------------
# AC1 + AC5 — CLI succeeds with sqlite+aiosqlite:// URL, no psycopg2
# ---------------------------------------------------------------------------


def test_create_recovery_token_succeeds_with_aiosqlite_url() -> None:
    """create-recovery-token exits 0 and prints a token when user exists (aiosqlite URL)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        async_url = _make_sqlite_async_url(db_path)
        _seed_user_sync(db_path, "admin@dojo.test")

        result = runner.invoke(
            cli_app,
            ["create-recovery-token", "admin@dojo.test"],
            env={"DATABASE_URL": async_url},
        )

        assert result.exit_code == 0, f"stdout={result.stdout!r} exc={result.exception}"
        assert len(result.stdout.strip()) > 0
    finally:
        os.unlink(db_path)


def test_create_recovery_token_token_is_nonempty_string() -> None:
    """Token printed to stdout is a non-empty, non-whitespace string."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        async_url = _make_sqlite_async_url(db_path)
        _seed_user_sync(db_path, "admin@dojo.test")

        result = runner.invoke(
            cli_app,
            ["create-recovery-token", "admin@dojo.test"],
            env={"DATABASE_URL": async_url},
        )

        token = result.stdout.strip()
        assert isinstance(token, str)
        assert len(token) > 8
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# AC2 — _get_engine() sync helper must be absent
# ---------------------------------------------------------------------------


def test_get_engine_not_present_in_cli_module() -> None:
    """_get_engine() must not exist in app.cli after the async rewrite."""
    import app.cli as cli_module

    assert not hasattr(
        cli_module, "_get_engine"
    ), "_get_engine() sync helper must be removed from cli.py"


# ---------------------------------------------------------------------------
# AC3 — asyncio.run (or equivalent) is used; create_engine is NOT called
# ---------------------------------------------------------------------------


def test_create_engine_not_imported_in_cli() -> None:
    """sqlalchemy.create_engine (sync) must not be imported or used in app.cli."""
    import ast
    import inspect

    import app.cli as cli_module

    source = inspect.getsource(cli_module)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        # Check for: from sqlalchemy import create_engine
        if isinstance(node, ast.ImportFrom):
            if node.module and "sqlalchemy" in node.module:
                names = [alias.name for alias in node.names]
                assert (
                    "create_engine" not in names
                ), "create_engine must not be imported in cli.py"
        # Check for: import sqlalchemy; sqlalchemy.create_engine(...)
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert (
                    alias.name != "sqlalchemy.create_engine"
                ), "create_engine must not be imported in cli.py"


def test_psycopg2_not_imported_in_cli() -> None:
    """psycopg2 must not be imported anywhere in the CLI module."""
    import ast
    import inspect

    import app.cli as cli_module

    source = inspect.getsource(cli_module)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in (
                node.names
                if isinstance(node, ast.Import)
                else [type("_", (), {"name": node.module or ""})()]
            ):
                assert "psycopg2" not in (
                    alias.name or ""
                ), "psycopg2 must not be imported in cli.py"


# ---------------------------------------------------------------------------
# AC6 — unknown email exits code 1 with error message
# ---------------------------------------------------------------------------


def test_create_recovery_token_unknown_email_exits_nonzero() -> None:
    """create-recovery-token with unknown email exits with non-zero code."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        async_url = _make_sqlite_async_url(db_path)
        _seed_user_sync(db_path, "admin@dojo.test")

        result = runner.invoke(
            cli_app,
            ["create-recovery-token", "nobody@notadojo.example"],
            env={"DATABASE_URL": async_url},
        )

        assert result.exit_code != 0
    finally:
        os.unlink(db_path)


def test_create_recovery_token_unknown_email_prints_error() -> None:
    """create-recovery-token with unknown email prints an error message to stderr."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        async_url = _make_sqlite_async_url(db_path)
        _seed_user_sync(db_path, "admin@dojo.test")

        result = runner.invoke(
            cli_app,
            ["create-recovery-token", "nobody@notadojo.example"],
            env={"DATABASE_URL": async_url},
        )

        # Typer's CliRunner: stderr goes to result.output, not result.stdout
        output = result.output or ""
        assert len(output.strip()) > 0
        # Should mention the email or "error"
        assert (
            "nobody@notadojo.example" in output.lower()
            or "error" in output.lower()
            or "not found" in output.lower()
        )
    finally:
        os.unlink(db_path)


def test_create_recovery_token_unknown_email_exits_code_1() -> None:
    """Exit code must be exactly 1 when user is not found."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        async_url = _make_sqlite_async_url(db_path)
        _seed_user_sync(db_path, "admin@dojo.test")

        result = runner.invoke(
            cli_app,
            ["create-recovery-token", "nobody@notadojo.example"],
            env={"DATABASE_URL": async_url},
        )

        assert result.exit_code == 1
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# AC7 — missing DATABASE_URL exits code 1 with error
# ---------------------------------------------------------------------------


def test_create_recovery_token_no_database_url_exits_nonzero() -> None:
    """create-recovery-token exits non-zero when DATABASE_URL is not set."""
    # Invoke with an env that explicitly has no DATABASE_URL
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "admin@dojo.test"],
        env={"DATABASE_URL": ""},
    )
    assert result.exit_code != 0


def test_create_recovery_token_no_database_url_exits_code_1() -> None:
    """Exit code must be exactly 1 when DATABASE_URL is absent."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "admin@dojo.test"],
        env={"DATABASE_URL": ""},
    )
    assert result.exit_code == 1


def test_create_recovery_token_no_database_url_prints_error() -> None:
    """Error message is printed when DATABASE_URL is not set."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "admin@dojo.test"],
        env={"DATABASE_URL": ""},
    )
    # Typer's CliRunner: stderr goes to result.output, not result.stdout
    output = result.output or ""
    assert len(output.strip()) > 0


# ---------------------------------------------------------------------------
# AC8 — AdminRecoveryToken is saved with correct fields (integration check)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_recovery_token_saves_token_row() -> None:
    """After a successful CLI invocation, one AdminRecoveryToken row is saved."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        async_url = _make_sqlite_async_url(db_path)
        user_id = _seed_user_sync(db_path, "admin@dojo.test")

        result = runner.invoke(
            cli_app,
            ["create-recovery-token", "admin@dojo.test"],
            env={"DATABASE_URL": async_url},
        )

        assert result.exit_code == 0, f"stdout={result.stdout!r} exc={result.exception}"

        # Verify token was persisted
        from sqlalchemy import select

        engine = create_async_engine(
            async_url, connect_args={"check_same_thread": False}
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AdminRecoveryToken).where(
                            AdminRecoveryToken.user_id == user_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        await engine.dispose()

        assert len(rows) == 1
    finally:
        os.unlink(db_path)


@pytest.mark.anyio
async def test_create_recovery_token_saves_null_created_by_id() -> None:
    """CLI-generated token has created_by_id = NULL (break-glass, no issuing admin)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        async_url = _make_sqlite_async_url(db_path)
        user_id = _seed_user_sync(db_path, "admin@dojo.test")

        result = runner.invoke(
            cli_app,
            ["create-recovery-token", "admin@dojo.test"],
            env={"DATABASE_URL": async_url},
        )

        assert result.exit_code == 0

        from sqlalchemy import select

        engine = create_async_engine(
            async_url, connect_args={"check_same_thread": False}
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AdminRecoveryToken).where(
                            AdminRecoveryToken.user_id == user_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        await engine.dispose()

        assert len(rows) == 1
        assert rows[0].created_by_id is None
    finally:
        os.unlink(db_path)
