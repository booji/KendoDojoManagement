"""Failing tests for issue #43 — CLI break-glass recovery token command.

Uses DB-backed integration tests (sqlite in-memory) matching the pattern
from test_admin_recovery.py.

Acceptance criteria exercised:
  AC1. `create-recovery-token <email>` prints a non-empty token to stdout
  AC2. Token stored in admin_recovery_tokens with created_by_id IS NULL
  AC3/AC6. CLI-generated token (created_by_id=NULL) redeems via POST /auth/recovery/redeem
  AC4. Unknown email exits non-zero with error message on stderr
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app.auth.db_models import AdminRecoveryToken, User

# CLI app import — will fail (ImportError) since app/cli.py does not exist yet.
from app.cli import app as cli_app  # noqa: E402  # red — cli.py doesn't exist
from app.db.base import Base
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_TARGET_EMAIL = "target@dojo.test"

runner = CliRunner()

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def _engine():
    eng = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_client(_engine):
    factory = async_sessionmaker(_engine, expire_on_commit=False)

    async def _override():
        async with SQLAlchemyUnitOfWork(factory) as uow:
            yield uow

    app.dependency_overrides[get_uow] = _override
    yield _engine


@pytest.fixture
def tmp_db():
    """A temporary file-based SQLite DB usable by both the CLI and async sessions."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    sync_url = f"sqlite:///{db_path}"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    yield {"sync_url": sync_url, "async_url": async_url, "path": db_path}

    os.unlink(db_path)


@pytest.fixture
def seeded_db():
    """Sync temp DB with admin@dojo.test pre-seeded, for AC1 synchronous test."""
    from sqlalchemy import create_engine as _ce

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    sync_url = f"sqlite:///{db_path}"
    engine = _ce(sync_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            User(
                id=str(uuid.uuid4()),
                email="admin@dojo.test",
                hashed_password=bcrypt.hashpw(b"unused", bcrypt.gensalt()).decode(),
                role="admin",
                is_active=True,
            )
        )
        session.commit()
    engine.dispose()
    yield sync_url
    os.unlink(db_path)


async def _seed_user(engine, email: str, user_id: str, *, role: str = "member") -> None:
    """Insert a user row into the test DB."""
    async with engine.begin() as conn:
        await conn.execute(
            insert(User).values(
                id=user_id,
                email=email,
                hashed_password=bcrypt.hashpw(b"unused", bcrypt.gensalt()).decode(),
                role=role,
                is_active=True,
            )
        )


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


# ── AC1 — CLI prints token to stdout ──────────────────────────────────────────


def test_cli_create_recovery_token_prints_to_stdout(seeded_db) -> None:
    """create-recovery-token with a known email prints a non-empty token to stdout."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "admin@dojo.test"],
        env={"DATABASE_URL": seeded_db},
    )
    assert result.exit_code == 0
    assert len(result.stdout.strip()) > 0


# ── AC2 — Token stored with created_by_id = NULL ──────────────────────────────


@pytest.mark.anyio
async def test_cli_token_stored_with_null_created_by_id(tmp_db) -> None:
    """After CLI invocation, one row exists in admin_recovery_tokens with created_by_id IS NULL."""
    target_id = str(uuid.uuid4())

    eng = create_async_engine(
        tmp_db["async_url"], connect_args={"check_same_thread": False}
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_user(eng, _TARGET_EMAIL, target_id)
    await eng.dispose()

    result = runner.invoke(
        cli_app,
        ["create-recovery-token", _TARGET_EMAIL],
        env={"DATABASE_URL": tmp_db["sync_url"]},
    )

    assert result.exit_code == 0

    eng2 = create_async_engine(
        tmp_db["async_url"], connect_args={"check_same_thread": False}
    )
    factory = async_sessionmaker(eng2, expire_on_commit=False)
    async with factory() as session:
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
    await eng2.dispose()

    assert len(rows) == 1
    assert rows[0].created_by_id is None


@pytest.mark.anyio
async def test_cli_token_only_one_row_created(tmp_db) -> None:
    """CLI command creates exactly one token row for the given user."""
    target_id = str(uuid.uuid4())

    eng = create_async_engine(
        tmp_db["async_url"], connect_args={"check_same_thread": False}
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_user(eng, _TARGET_EMAIL, target_id)
    await eng.dispose()

    runner.invoke(
        cli_app,
        ["create-recovery-token", _TARGET_EMAIL],
        env={"DATABASE_URL": tmp_db["sync_url"]},
    )

    eng2 = create_async_engine(
        tmp_db["async_url"], connect_args={"check_same_thread": False}
    )
    factory = async_sessionmaker(eng2, expire_on_commit=False)
    async with factory() as session:
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
    await eng2.dispose()

    assert len(rows) == 1


# ── AC3/AC6 — CLI-generated token (created_by_id=NULL) redeems via redeem endpoint ──


@pytest.mark.anyio
async def test_cli_generated_token_redeems_returns_200(db_client) -> None:
    """Seed a CLI-style token (created_by_id=NULL) and redeem via POST /auth/recovery/redeem → 200."""
    target_id = str(uuid.uuid4())
    await _seed_user(db_client, _TARGET_EMAIL, target_id)
    plaintext = "cli-break-glass-token-abcd"
    # Seed with created_by_id=None to simulate CLI-generated token
    await _seed_admin_token(db_client, target_id, plaintext, created_by_id=None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": _TARGET_EMAIL, "code": plaintext},
        )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_cli_generated_token_redeems_returns_access_token(db_client) -> None:
    """Redeeming a CLI-generated token (created_by_id=NULL) returns a JWT access_token."""
    target_id = str(uuid.uuid4())
    await _seed_user(db_client, _TARGET_EMAIL, target_id)
    plaintext = "cli-break-glass-token-abcd"
    await _seed_admin_token(db_client, target_id, plaintext, created_by_id=None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": _TARGET_EMAIL, "code": plaintext},
        )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert isinstance(body["access_token"], str)
    assert len(body["access_token"]) > 0


@pytest.mark.anyio
async def test_cli_generated_token_marked_used_after_redeem(db_client) -> None:
    """After redeeming a CLI-generated token, used_at is set on the row."""
    target_id = str(uuid.uuid4())
    await _seed_user(db_client, _TARGET_EMAIL, target_id)
    plaintext = "cli-break-glass-token-abcd"
    token_id = await _seed_admin_token(
        db_client, target_id, plaintext, created_by_id=None
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": _TARGET_EMAIL, "code": plaintext},
        )

    assert response.status_code == 200

    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(AdminRecoveryToken, token_id)

    assert row is not None
    assert row.used_at is not None


# ── AC4 — Unknown email exits non-zero with error on stderr ───────────────────


def test_cli_unknown_email_exits_nonzero(seeded_db) -> None:
    """create-recovery-token with an email not in the DB exits with a non-zero code."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "nobody@notadojo.example"],
        env={"DATABASE_URL": seeded_db},
    )
    assert result.exit_code != 0


def test_cli_unknown_email_prints_error_message(seeded_db) -> None:
    """create-recovery-token with an unknown email prints an error message."""
    result = runner.invoke(
        cli_app,
        ["create-recovery-token", "nobody@notadojo.example"],
        env={"DATABASE_URL": seeded_db},
    )
    # The error may go to stdout or stderr depending on Typer's runner behaviour.
    # We check both: at least one must contain a non-empty error message.
    output = (result.stdout or "") + (
        result.stderr if hasattr(result, "stderr") and result.stderr else ""
    )
    assert len(output.strip()) > 0
