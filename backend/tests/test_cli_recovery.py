"""Failing tests for issue #43 — CLI break-glass recovery token command.

Uses DB-backed integration tests against the shared PostgreSQL test database
matching the pattern from test_admin_recovery.py.

Acceptance criteria exercised:
  AC1. `create-recovery-token <email>` prints a non-empty token to stdout
  AC2. Token stored in admin_recovery_tokens with created_by_id IS NULL
  AC3/AC6. CLI-generated token (created_by_id=NULL) redeems via POST /auth/recovery/redeem
  AC4. Unknown email exits non-zero with error message on stderr
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from typer.testing import CliRunner

from app.auth.db_models import Account, AdminRecoveryToken, RecoveryAttempt

# CLI app import — will fail (ImportError) since app/cli.py does not exist yet.
from app.cli import app as cli_app  # noqa: E402  # red — cli.py doesn't exist
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app
from tests.account_support import seed_account

runner = CliRunner()

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def db_client(database_url: str):
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with SQLAlchemyUnitOfWork(factory) as uow:
            yield uow

    app.dependency_overrides[get_uow] = _override
    yield engine
    await engine.dispose()


@pytest.fixture
def tmp_db(database_url: str) -> str:
    """The shared PostgreSQL test database URL, usable by both the CLI
    (as a subprocess-style env var) and async sessions in the test body.

    Named `tmp_db` (rather than renaming every call site) because it plays
    the same role the old per-test embedded-file DB played: a DATABASE_URL the
    CLI and an async session both point at.
    """
    return database_url


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4()}@dojo.test"


@pytest_asyncio.fixture
async def seeded_db(database_url: str):
    """PostgreSQL test DB with a uniquely-emailed admin user pre-seeded, for
    AC1. Yields {"url": ..., "email": ...} and cleans up the seeded user
    (and anything the CLI created for them) on teardown."""
    email = _unique_email("cli-seeded")
    user_id = str(uuid.uuid4())
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as session:
            await seed_account(
                session, email, user_id=user_id, role="admin", is_active=True
            )
            await session.commit()

        yield {"url": database_url, "email": email}

        async with AsyncSession(engine) as session:
            await session.execute(
                delete(RecoveryAttempt).where(RecoveryAttempt.user_id == user_id)
            )
            await session.execute(
                delete(AdminRecoveryToken).where(AdminRecoveryToken.user_id == user_id)
            )
            await session.execute(delete(Account).where(Account.id == user_id))
            await session.commit()
    finally:
        await engine.dispose()


async def _seed_user(engine, email: str, user_id: str, *, role: str = "member") -> None:
    """Insert a user row into the test DB."""
    async with engine.begin() as conn:
        await seed_account(conn, email, user_id=user_id, role=role, is_active=True)


async def _seed_admin_token(
    engine,
    user_id: str,
    plaintext: str,
    *,
    expires_at: datetime | None = None,
    used: bool = False,
    created_by_id: str | None = None,
) -> str:
    """Insert an admin_recovery_token row and return its id."""
    token_id = str(uuid.uuid4())
    token_hash = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()
    now = datetime.now(UTC)
    if expires_at is None:
        expires_at = now + timedelta(minutes=60)
    async with engine.begin() as conn:
        await conn.execute(
            insert(AdminRecoveryToken).values(
                id=token_id,
                user_id=user_id,
                created_by_id=created_by_id,
                token_hash=token_hash,
                expires_at=expires_at,
                used_at=now if used else None,
                created_at=now,
            )
        )
    return token_id


async def _delete_target(engine, user_id: str) -> None:
    """Clean up a seeded target user and any recovery attempts/tokens it
    accumulated (the /auth/recovery/redeem endpoint logs a RecoveryAttempt
    row on every call, including failed ones)."""
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(RecoveryAttempt).where(RecoveryAttempt.user_id == user_id)
        )
        await session.execute(
            delete(AdminRecoveryToken).where(AdminRecoveryToken.user_id == user_id)
        )
        await session.execute(delete(Account).where(Account.id == user_id))
        await session.commit()


# ── AC1 — CLI prints token to stdout ──────────────────────────────────────────


def test_cli_create_recovery_token_prints_to_stdout(seeded_db) -> None:
    """create-recovery-token with a known email prints a non-empty token to stdout."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", seeded_db["email"]],
        env={"DATABASE_URL": seeded_db["url"]},
    )
    assert result.exit_code == 0
    assert len(result.stdout.strip()) > 0


# ── AC2 — Token stored with created_by_id = NULL ──────────────────────────────


@pytest.mark.asyncio
async def test_cli_token_stored_with_null_created_by_id(tmp_db) -> None:
    """After CLI invocation, one row exists in admin_recovery_tokens with created_by_id IS NULL."""
    target_id = str(uuid.uuid4())
    target_email = _unique_email("cli-null-created-by")

    eng = create_async_engine(tmp_db, poolclass=NullPool)
    try:
        await _seed_user(eng, target_email, target_id)

        result = runner.invoke(
            cli_app,
            ["create-recovery-token", target_email],
            env={"DATABASE_URL": tmp_db},
        )

        assert result.exit_code == 0

        async with AsyncSession(eng) as session:
            rows = (
                (
                    await session.execute(
                        select(AdminRecoveryToken).where(
                            AdminRecoveryToken.user_id == target_id
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 1
        assert rows[0].created_by_id is None
    finally:
        async with AsyncSession(eng) as session:
            await session.execute(
                delete(AdminRecoveryToken).where(
                    AdminRecoveryToken.user_id == target_id
                )
            )
            await session.execute(delete(Account).where(Account.id == target_id))
            await session.commit()
        await eng.dispose()


@pytest.mark.asyncio
async def test_cli_token_only_one_row_created(tmp_db) -> None:
    """CLI command creates exactly one token row for the given user."""
    target_id = str(uuid.uuid4())
    target_email = _unique_email("cli-one-row")

    eng = create_async_engine(tmp_db, poolclass=NullPool)
    try:
        await _seed_user(eng, target_email, target_id)

        runner.invoke(
            cli_app,
            ["create-recovery-token", target_email],
            env={"DATABASE_URL": tmp_db},
        )

        async with AsyncSession(eng) as session:
            rows = (
                (
                    await session.execute(
                        select(AdminRecoveryToken).where(
                            AdminRecoveryToken.user_id == target_id
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 1
    finally:
        async with AsyncSession(eng) as session:
            await session.execute(
                delete(AdminRecoveryToken).where(
                    AdminRecoveryToken.user_id == target_id
                )
            )
            await session.execute(delete(Account).where(Account.id == target_id))
            await session.commit()
        await eng.dispose()


# ── AC3/AC6 — CLI-generated token (created_by_id=NULL) redeems via redeem endpoint ──


@pytest.mark.asyncio
async def test_cli_generated_token_redeems_returns_200(db_client) -> None:
    """Seed a CLI-style token (created_by_id=NULL) and redeem via POST /auth/recovery/redeem → 200."""
    target_id = str(uuid.uuid4())
    target_email = _unique_email("cli-redeem-200")
    await _seed_user(db_client, target_email, target_id)
    plaintext = "cli-break-glass-token-abcd"
    # Seed with created_by_id=None to simulate CLI-generated token
    await _seed_admin_token(db_client, target_id, plaintext, created_by_id=None)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/auth/recovery/redeem",
                json={"email": target_email, "code": plaintext},
            )

        assert response.status_code == 200
    finally:
        await _delete_target(db_client, target_id)


@pytest.mark.asyncio
async def test_cli_generated_token_redeems_returns_access_token(db_client) -> None:
    """Redeeming a CLI-generated token (created_by_id=NULL) returns a JWT access_token."""
    target_id = str(uuid.uuid4())
    target_email = _unique_email("cli-redeem-token")
    await _seed_user(db_client, target_email, target_id)
    plaintext = "cli-break-glass-token-abcd"
    await _seed_admin_token(db_client, target_id, plaintext, created_by_id=None)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/auth/recovery/redeem",
                json={"email": target_email, "code": plaintext},
            )

        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert isinstance(body["access_token"], str)
        assert len(body["access_token"]) > 0
    finally:
        await _delete_target(db_client, target_id)


@pytest.mark.asyncio
async def test_cli_generated_token_marked_used_after_redeem(db_client) -> None:
    """After redeeming a CLI-generated token, used_at is set on the row."""
    target_id = str(uuid.uuid4())
    target_email = _unique_email("cli-redeem-used")
    await _seed_user(db_client, target_email, target_id)
    plaintext = "cli-break-glass-token-abcd"
    token_id = await _seed_admin_token(
        db_client, target_id, plaintext, created_by_id=None
    )

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/auth/recovery/redeem",
                json={"email": target_email, "code": plaintext},
            )

        assert response.status_code == 200

        factory = async_sessionmaker(db_client, expire_on_commit=False)
        async with factory() as session:
            row = await session.get(AdminRecoveryToken, token_id)

        assert row is not None
        assert row.used_at is not None
    finally:
        await _delete_target(db_client, target_id)


# ── AC4 — Unknown email exits non-zero with error on stderr ───────────────────


def test_cli_unknown_email_exits_nonzero(seeded_db) -> None:
    """create-recovery-token with an email not in the DB exits with a non-zero code."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "nobody@notadojo.example"],
        env={"DATABASE_URL": seeded_db["url"]},
    )
    assert result.exit_code != 0


def test_cli_unknown_email_prints_error_message(seeded_db) -> None:
    """create-recovery-token with an unknown email prints an error message."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "nobody@notadojo.example"],
        env={"DATABASE_URL": seeded_db["url"]},
    )
    # The error may go to stdout or stderr depending on Typer's runner behaviour.
    # We check both: at least one must contain a non-empty error message.
    output = (result.stdout or "") + (
        result.stderr if hasattr(result, "stderr") and result.stderr else ""
    )
    assert len(output.strip()) > 0
