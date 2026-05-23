"""Failing tests for issue #41 — Recovery code redemption + rate limiting.

Uses a mix of:
- Direct model-field checks (will fail with ImportError until model exists)
- DB-backed integration tests via db_client fixture (will fail with 404 until route exists)
- Stub-based tests for route guard behaviour

Acceptance criteria exercised:
  AC1. recovery_attempts table fields
  AC2. POST /auth/recovery/redeem returns restricted JWT
  AC3. Restricted JWT blocked on regular guarded routes
  AC5. Used code rejected with 401
  AC6. 5 failures → 429
  AC7. All attempts logged
  AC9. Unit: valid→used; used→rejected; wrong→counter++; 5th→429; success resets counter
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.db_models import RecoveryCode, User
from app.auth.models import UserClaims
from app.db.base import Base
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_USER = UserClaims(
    sub=str(uuid.uuid4()), email="musashi@dojo.test", role="member", is_active=True
)

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


async def _seed_user(engine, email: str, user_id: str) -> None:
    """Insert a user row into the test DB."""
    async with engine.begin() as conn:
        await conn.execute(
            insert(User).values(
                id=user_id,
                email=email,
                role="member",
                is_active=True,
            )
        )


async def _seed_recovery_code(
    engine,
    user_id: str,
    plaintext: str,
    used: bool = False,
) -> str:
    """Insert a recovery code row and return its id."""
    code_id = str(uuid.uuid4())
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await conn.execute(
            insert(RecoveryCode).values(
                id=code_id,
                user_id=user_id,
                code_hash=hashed,
                set_id=str(uuid.uuid4()),
                used_at=now if used else None,
                created_at=now,
            )
        )
    return code_id


async def _seed_failed_attempt(engine, user_id: str, count: int = 1) -> None:
    """Insert n failed recovery_attempts rows for rate-limit tests."""
    from app.auth.db_models import RecoveryAttempt  # red — model doesn't exist yet

    now = datetime.now(UTC)
    async with engine.begin() as conn:
        for _ in range(count):
            await conn.execute(
                insert(RecoveryAttempt).values(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    attempted_at=now,
                    ip_address="127.0.0.1",
                    success=False,
                )
            )


# ── AC1 — Model field tests ────────────────────────────────────────────────────


def test_recovery_attempt_model_has_id_field() -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    assert hasattr(RecoveryAttempt, "id")


def test_recovery_attempt_model_has_user_id_field() -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    assert hasattr(RecoveryAttempt, "user_id")


def test_recovery_attempt_model_has_attempted_at_field() -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    assert hasattr(RecoveryAttempt, "attempted_at")


def test_recovery_attempt_model_has_ip_address_field() -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    assert hasattr(RecoveryAttempt, "ip_address")


def test_recovery_attempt_model_has_success_field() -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    assert hasattr(RecoveryAttempt, "success")


# ── AC2 — POST /auth/recovery/redeem returns restricted JWT ────────────────────


@pytest.mark.anyio
async def test_redeem_valid_code_returns_200(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_redeem_valid_code_returns_access_token(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    body = response.json()
    assert "access_token" in body


@pytest.mark.anyio
async def test_redeem_token_has_recovery_session_claim(db_client) -> None:
    """Returned JWT must carry recovery_session: true."""
    from joserfc import jwt
    from joserfc.jwk import OctKey

    from app import config

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    assert response.status_code == 200
    token = response.json()["access_token"]
    key = OctKey.import_key(config.JWT_SECRET.encode())
    decoded = jwt.decode(token, key, algorithms=["HS256"])
    assert decoded.claims.get("recovery_session") is True


@pytest.mark.anyio
async def test_redeem_token_expires_in_15_minutes(db_client) -> None:
    """Returned JWT must expire in approximately 15 minutes."""
    from joserfc import jwt
    from joserfc.jwk import OctKey

    from app import config

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    before = datetime.now(UTC)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    assert response.status_code == 200
    token = response.json()["access_token"]
    key = OctKey.import_key(config.JWT_SECRET.encode())
    decoded = jwt.decode(token, key, algorithms=["HS256"])
    exp = datetime.fromtimestamp(decoded.claims["exp"], tz=UTC)
    delta = exp - before
    assert timedelta(minutes=14) < delta < timedelta(minutes=16)


# ── AC3 — Route guard blocks recovery JWT on regular endpoints ─────────────────


@pytest.mark.anyio
async def test_recovery_token_blocked_on_regular_guarded_route(db_client) -> None:
    """GET /auth/me with a recovery JWT should return 403."""
    from app.auth.token import encode_recovery_token  # red — doesn't exist yet

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    token = encode_recovery_token(user_id=user_id, email="musashi@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"access_token": token},
    ) as c:
        response = await c.get("/auth/me")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_recovery_token_blocked_on_members_list(db_client) -> None:
    """GET /members with a recovery JWT should return 403."""
    from app.auth.token import encode_recovery_token  # red

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    token = encode_recovery_token(user_id=user_id, email="musashi@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"access_token": token},
    ) as c:
        response = await c.get("/members")

    assert response.status_code == 403


# ── AC5 — Used code rejected with 401 ─────────────────────────────────────────


@pytest.mark.anyio
async def test_redeem_used_code_returns_401(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext, used=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_redeem_wrong_code_returns_401(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_recovery_code(db_client, user_id, "real-code-xxxx")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": "wrong-code-yyyy"},
        )

    assert response.status_code == 401


# ── AC6 — 5 failures → 429 ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_fifth_failed_attempt_returns_429(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_recovery_code(db_client, user_id, "real-code-xxxx")
    await _seed_failed_attempt(db_client, user_id, count=4)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": "wrong-code-yyyy"},
        )

    assert response.status_code == 429


@pytest.mark.anyio
async def test_four_failures_still_allows_attempt(db_client) -> None:
    """3 prior failures: 4th attempt with valid code should succeed."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    await _seed_failed_attempt(db_client, user_id, count=3)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    assert response.status_code == 200


# ── AC7 — Attempts logged ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_successful_redemption_logs_attempt(db_client) -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(RecoveryAttempt).where(RecoveryAttempt.user_id == user_id)
        )
        attempts = result.scalars().all()
    assert len(attempts) == 1
    assert attempts[0].success is True


@pytest.mark.anyio
async def test_failed_redemption_logs_attempt(db_client) -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_recovery_code(db_client, user_id, "real-code-xxxx")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": "wrong-code-yyyy"},
        )

    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(RecoveryAttempt).where(RecoveryAttempt.user_id == user_id)
        )
        attempts = result.scalars().all()
    assert len(attempts) == 1
    assert attempts[0].success is False


# ── AC9 — Unit behaviour ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_valid_code_is_marked_used_after_redemption(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    code_id = await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    assert response.status_code == 200
    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(RecoveryCode, code_id)
    assert row is not None
    assert row.used_at is not None


@pytest.mark.anyio
async def test_wrong_code_increments_attempt_counter(db_client) -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_recovery_code(db_client, user_id, "real-code-xxxx")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(2):
            await c.post(
                "/auth/recovery/redeem",
                json={"email": "musashi@dojo.test", "code": "wrong-code-yyyy"},
            )

    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(RecoveryAttempt).where(
                RecoveryAttempt.user_id == user_id,
                RecoveryAttempt.success.is_(False),
            )
        )
        rows = result.scalars().all()
    assert len(rows) == 2


@pytest.mark.anyio
async def test_successful_attempt_after_prior_failures_resets_counter(
    db_client,
) -> None:
    """After a successful redemption, 4 new failures should NOT trigger 429."""

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    # Seed 3 earlier failures (before the success)
    await _seed_failed_attempt(db_client, user_id, count=3)

    # Successful redemption — should reset the failure counter
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        success_resp = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )
    assert success_resp.status_code == 200

    # Seed new codes and make 4 fresh failures
    plaintext2 = "mnop-qrst-uvwx"
    await _seed_recovery_code(db_client, user_id, plaintext2)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(4):
            r = await c.post(
                "/auth/recovery/redeem",
                json={"email": "musashi@dojo.test", "code": "wrong-code-yyyy"},
            )
        # 4th new failure: should still be 401 (not 429) because counter was reset
        assert r.status_code == 401


@pytest.mark.anyio
async def test_used_code_double_redemption_returns_401(db_client) -> None:
    """Redeeming the same valid code twice: second attempt returns 401."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r1 = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )
        r2 = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    assert r1.status_code == 200
    assert r2.status_code == 401
