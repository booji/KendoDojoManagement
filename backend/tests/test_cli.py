"""Failing tests for issue #153 — async CLI rewrite for create-recovery-token.

The current CLI uses a sync _get_engine() that strips '+asyncpg', leaving a bare
'postgresql://' URL which SQLAlchemy routes to psycopg2 — not installed.

Fix direction: rewrite CLI to be async, drop _get_engine(), use an async
SQLAlchemy session created from DATABASE_URL directly.

Acceptance criteria:
  AC1. create-recovery-token succeeds against the real DATABASE_URL — no psycopg2
  AC2. _get_engine() sync helper is gone from cli.py
  AC3. CLI uses asyncio.run wrapping async commands
  AC4. No new packages added
  AC5. Works against the shared PostgreSQL test database (dev/test compat)
  AC6. Exits code 1 + error when user not found
  AC7. Exits code 1 + error when DATABASE_URL not set
  AC8. create_engine / psycopg2 are never imported or called in the CLI path

Each test seeds its own Account row with a unique, uuid-suffixed email against
the shared PostgreSQL test database (via the `database_url` fixture) rather
than a private per-test embedded-file DB, then cleans up the rows it created —
there is no per-test throwaway database to rely on for isolation here.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from typer.testing import CliRunner

from app.auth.db_models import Account, AdminRecoveryToken
from app.cli import app as cli_app
from tests.account_support import seed_account

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_user(database_url: str, email: str) -> str:
    """Seed a user row against the real test database so the CLI can find it."""
    user_id = str(uuid.uuid4())
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as session:
            await seed_account(session, email, user_id=user_id, role="admin")
            await session.commit()
    finally:
        await engine.dispose()
    return user_id


async def _cleanup_user(database_url: str, user_id: str) -> None:
    """Delete a seeded user and any recovery tokens it accumulated."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as session:
            await session.execute(
                delete(AdminRecoveryToken).where(AdminRecoveryToken.user_id == user_id)
            )
            await session.execute(delete(Account).where(Account.id == user_id))
            await session.commit()
    finally:
        await engine.dispose()


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4()}@dojo.test"


# ---------------------------------------------------------------------------
# AC1 + AC5 — CLI succeeds against the real DATABASE_URL, no psycopg2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_recovery_token_succeeds_with_real_database_url(
    database_url: str,
) -> None:
    """create-recovery-token exits 0 and prints a token when the user exists."""
    email = _unique_email("cli-succeeds")
    user_id = await _seed_user(database_url, email)
    try:
        result = runner.invoke(
            cli_app,
            ["create-recovery-token", email],
            env={"DATABASE_URL": database_url},
        )

        assert result.exit_code == 0, f"stdout={result.stdout!r} exc={result.exception}"
        assert len(result.stdout.strip()) > 0
    finally:
        await _cleanup_user(database_url, user_id)


@pytest.mark.asyncio
async def test_create_recovery_token_reads_the_database_url_file(
    database_url: str, tmp_path
) -> None:
    """Inside the hardened app container the login is a mounted file and
    DATABASE_URL is unset (#462): break-glass must still work there."""
    email = _unique_email("cli-url-file")
    user_id = await _seed_user(database_url, email)
    url_file = tmp_path / "database_url"
    url_file.write_text(database_url)
    try:
        result = runner.invoke(
            cli_app,
            ["create-recovery-token", email],
            env={"DATABASE_URL": "", "DATABASE_URL_FILE": str(url_file)},
        )

        assert result.exit_code == 0, f"output={result.output!r} exc={result.exception}"
        assert len(result.stdout.strip()) > 0
    finally:
        await _cleanup_user(database_url, user_id)


@pytest.mark.asyncio
async def test_create_recovery_token_token_is_nonempty_string(
    database_url: str,
) -> None:
    """Token printed to stdout is a non-empty, non-whitespace string."""
    email = _unique_email("cli-nonempty")
    user_id = await _seed_user(database_url, email)
    try:
        result = runner.invoke(
            cli_app,
            ["create-recovery-token", email],
            env={"DATABASE_URL": database_url},
        )

        token = result.stdout.strip()
        assert isinstance(token, str)
        assert len(token) > 8
    finally:
        await _cleanup_user(database_url, user_id)


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


def test_create_recovery_token_unknown_email_exits_nonzero(database_url: str) -> None:
    """create-recovery-token with unknown email exits with non-zero code."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "nobody@notadojo.example"],
        env={"DATABASE_URL": database_url},
    )

    assert result.exit_code != 0


def test_create_recovery_token_unknown_email_prints_error(database_url: str) -> None:
    """create-recovery-token with unknown email prints an error message to stderr."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "nobody@notadojo.example"],
        env={"DATABASE_URL": database_url},
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


def test_create_recovery_token_unknown_email_exits_code_1(database_url: str) -> None:
    """Exit code must be exactly 1 when user is not found."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "nobody@notadojo.example"],
        env={"DATABASE_URL": database_url},
    )

    assert result.exit_code == 1


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


@pytest.mark.asyncio
async def test_create_recovery_token_saves_token_row(database_url: str) -> None:
    """After a successful CLI invocation, one AdminRecoveryToken row is saved."""
    email = _unique_email("cli-saves-row")
    user_id = await _seed_user(database_url, email)
    try:
        result = runner.invoke(
            cli_app,
            ["create-recovery-token", email],
            env={"DATABASE_URL": database_url},
        )

        assert result.exit_code == 0, f"stdout={result.stdout!r} exc={result.exception}"

        # Verify token was persisted
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine) as session:
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
        finally:
            await engine.dispose()

        assert len(rows) == 1
    finally:
        await _cleanup_user(database_url, user_id)


@pytest.mark.asyncio
async def test_create_recovery_token_saves_null_created_by_id(
    database_url: str,
) -> None:
    """CLI-generated token has created_by_id = NULL (break-glass, no issuing admin)."""
    email = _unique_email("cli-null-created-by")
    user_id = await _seed_user(database_url, email)
    try:
        result = runner.invoke(
            cli_app,
            ["create-recovery-token", email],
            env={"DATABASE_URL": database_url},
        )

        assert result.exit_code == 0

        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine) as session:
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
        finally:
            await engine.dispose()

        assert len(rows) == 1
        assert rows[0].created_by_id is None
    finally:
        await _cleanup_user(database_url, user_id)
