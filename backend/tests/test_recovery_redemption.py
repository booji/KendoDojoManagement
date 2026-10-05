"""Failing tests for issue #41 — Recovery code redemption + rate limiting.

Uses a mix of:
- Direct model-field checks (will fail with ImportError until model exists)
- DB-backed integration tests via db_client fixture (own NullPool engine
  against the shared PostgreSQL test database, real commits -- needed since
  several tests exercise rate-limit counters across multiple independent
  HTTP requests, each opening its own session via get_uow) (will fail with
  404 until route exists)
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
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.db_models import Account, AuthSession, RecoveryAttempt, RecoveryCode
from app.auth.models import AccountClaims
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app
from app.members.db_models import Member
from tests.account_support import seed_account

_TEST_EMAIL = "musashi@dojo.test"

_USER = AccountClaims(
    sub=str(uuid.uuid4()), email=_TEST_EMAIL, role="member", is_active=True
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


async def _wipe_test_email(engine, email: str = _TEST_EMAIL) -> None:
    """Delete any leftover row for _TEST_EMAIL and its dependents.

    Every test in this file seeds the same literal email (several assertions
    depend on that literal appearing in request/response bodies), and this
    fixture commits for real against the shared PostgreSQL test database (no
    savepoint rollback -- several tests need real cross-request commits to
    exercise rate-limit counters). Without this, the second test to seed
    that email hits a unique-constraint violation.
    """
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(Account.id)
            .join(Member, Member.id == Account.member_id)
            .where(Member.email == email)
        )
        user_ids = [row[0] for row in result.all()]
        if user_ids:
            await session.execute(
                delete(RecoveryAttempt).where(RecoveryAttempt.user_id.in_(user_ids))
            )
            await session.execute(
                delete(RecoveryCode).where(RecoveryCode.user_id.in_(user_ids))
            )
            await session.execute(delete(Account).where(Account.id.in_(user_ids)))
            await session.commit()


@pytest.fixture
async def db_client(database_url: str):
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with SQLAlchemyUnitOfWork(factory) as uow:
            yield uow

    await _wipe_test_email(engine)
    app.dependency_overrides[get_uow] = _override
    yield engine
    await _wipe_test_email(engine)
    await engine.dispose()


async def _seed_user(engine, email: str, user_id: str) -> None:
    """Insert a user row into the test DB."""
    async with engine.begin() as conn:
        await seed_account(conn, email, user_id=user_id, role="member", is_active=True)


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


async def _seed_failed_attempt(
    engine, user_id: str, count: int = 1, attempted_at: datetime | None = None
) -> None:
    """Insert n failed recovery_attempts rows for rate-limit tests."""
    from app.auth.db_models import RecoveryAttempt  # red — model doesn't exist yet

    now = attempted_at or datetime.now(UTC)
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


@pytest.mark.asyncio
async def test_redeem_valid_code_returns_200(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_redeem_valid_code_returns_access_token(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    body = response.json()
    assert "access_token" in body


async def _redeemed_token(db_client) -> tuple[str, str]:
    """(Account id, recovery token) after redeeming a fresh recovery code."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )
    assert response.status_code == 200
    return user_id, response.json()["access_token"]


@pytest.mark.asyncio
async def test_redeem_token_is_a_recovery_auth_session(db_client) -> None:
    """The token names an Auth Session row of kind ``recovery`` (#486)."""
    user_id, _ = await _redeemed_token(db_client)

    async with db_client.connect() as conn:
        result = await conn.execute(
            select(AuthSession.kind).where(AuthSession.account_id == user_id)
        )
        kinds = result.scalars().all()
    assert kinds == ["recovery"]


@pytest.mark.asyncio
async def test_redeem_token_expires_in_15_minutes(db_client) -> None:
    user_id, _ = await _redeemed_token(db_client)

    async with db_client.connect() as conn:
        created_at, expires_at = (
            await conn.execute(
                select(AuthSession.created_at, AuthSession.expires_at).where(
                    AuthSession.account_id == user_id
                )
            )
        ).one()
    assert expires_at - created_at == timedelta(minutes=15)


# ── AC3 — Route guard blocks a recovery token on regular endpoints ────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/auth/me", "/members"])
async def test_recovery_token_blocked_on_guarded_routes(db_client, path) -> None:
    """A recovery token is a live Auth Session, but only for enrolling a
    passkey: on any other route it is a 403, wherever it is sent."""
    _, token = await _redeemed_token(db_client)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api",
        cookies={"access_token": token},
    ) as c:
        response = await c.get(path)

    assert response.status_code == 403


# ── AC5 — Used code rejected with 401 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_redeem_used_code_returns_401(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext, used=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_redeem_wrong_code_returns_401(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_recovery_code(db_client, user_id, "real-code-xxxx")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": "wrong-code-yyyy"},
        )

    assert response.status_code == 401


# ── AC6 — 5 failures → 429 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fifth_failed_attempt_returns_429(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_recovery_code(db_client, user_id, "real-code-xxxx")
    await _seed_failed_attempt(db_client, user_id, count=4)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": "wrong-code-yyyy"},
        )

    assert response.status_code == 429


@pytest.mark.asyncio
async def test_four_failures_still_allows_attempt(db_client) -> None:
    """3 prior failures: 4th attempt with valid code should succeed."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    await _seed_failed_attempt(db_client, user_id, count=3)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )

    assert response.status_code == 200


# ── AC7 — Attempts logged ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_redemption_logs_attempt(db_client) -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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


@pytest.mark.asyncio
async def test_failed_redemption_logs_attempt(db_client) -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_recovery_code(db_client, user_id, "real-code-xxxx")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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


@pytest.mark.asyncio
async def test_valid_code_is_marked_used_after_redemption(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    code_id = await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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


@pytest.mark.asyncio
async def test_wrong_code_increments_attempt_counter(db_client) -> None:
    from app.auth.db_models import RecoveryAttempt  # red

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_recovery_code(db_client, user_id, "real-code-xxxx")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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


@pytest.mark.asyncio
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
        transport=ASGITransport(app=app), base_url="http://test/api"
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
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        for _ in range(4):
            r = await c.post(
                "/auth/recovery/redeem",
                json={"email": "musashi@dojo.test", "code": "wrong-code-yyyy"},
            )
        # 4th new failure: should still be 401 (not 429) because counter was reset
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_used_code_double_redemption_returns_401(db_client) -> None:
    """Redeeming the same valid code twice: second attempt returns 401."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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


# ── #434 — Retention of attempt rows and their IP addresses ───────────────────


async def _attempts_for(engine, user_id: str) -> list[RecoveryAttempt]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(RecoveryAttempt).where(RecoveryAttempt.user_id == user_id)
        )
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_success_deletes_the_accounts_earlier_attempts(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    await _seed_failed_attempt(db_client, user_id, count=3)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        r = await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": plaintext},
        )
    assert r.status_code == 200

    attempts = await _attempts_for(db_client, user_id)
    assert [a.success for a in attempts] == [True]


@pytest.mark.asyncio
async def test_log_attempt_clears_ip_addresses_older_than_30_days(db_client) -> None:
    """Every Account's aged rows lose their IP; the rows themselves stay."""
    now = datetime.now(UTC)
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_recovery_code(db_client, user_id, "real-code-xxxx")
    await _seed_failed_attempt(
        db_client, user_id, attempted_at=now - timedelta(days=29)
    )
    # An Account that never tries again still has its old IPs cleared.
    other_email = "kojiro@dojo.test"
    other_id = str(uuid.uuid4())
    await _seed_user(db_client, other_email, other_id)
    try:
        await _seed_failed_attempt(
            db_client, other_id, attempted_at=now - timedelta(days=31)
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            r = await c.post(
                "/auth/recovery/redeem",
                json={"email": "musashi@dojo.test", "code": "wrong-code-yyyy"},
            )
        assert r.status_code == 401

        others = await _attempts_for(db_client, other_id)
        assert [(a.ip_address, a.success) for a in others] == [(None, False)]
        mine = await _attempts_for(db_client, user_id)
        assert [a.ip_address for a in mine] == ["127.0.0.1", "127.0.0.1"]
    finally:
        await _wipe_test_email(db_client, other_email)
