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
  AC6. 5 failures lock recovery (answered as a bad code, #588)
  AC7. All attempts logged
  AC9. Unit: valid→used; used→rejected; wrong→counter++; 5th→locked; success resets counter
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import config
from app.auth.attempt_repository import SqlAttemptRepository
from app.auth.db_models import (
    Account,
    AdminRecoveryToken,
    AuthSession,
    RecoveryAttempt,
    RecoveryCode,
)
from app.auth.schemas import AccountClaims
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app
from app.members.db_models import Member
from tests.account_support import seed_account
from tests.timing_support import assert_latency_converges_sampled

_TEST_EMAIL = "musashi@dojo.test"

_USER = AccountClaims(sub=str(uuid.uuid4()), email=_TEST_EMAIL, role="member")

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
                delete(AdminRecoveryToken).where(
                    AdminRecoveryToken.user_id.in_(user_ids)
                )
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


async def _seed_user(
    engine, email: str, user_id: str, membership_status: str = "active"
) -> None:
    """Insert a user row into the test DB.

    The Member outlives `_wipe_test_email`, which deletes only Accounts, so
    its status is set every time rather than inherited from an earlier test.
    """
    async with engine.begin() as conn:
        await seed_account(conn, email, user_id=user_id, role="member")
        await conn.execute(
            update(Member)
            .where(Member.email == email)
            .values(membership_status=membership_status)
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
async def test_redeem_ignores_the_case_of_the_email(db_client) -> None:
    # #592: the address is stored folded; the Member may type it any way.
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": "Musashi@Dojo.test", "code": plaintext},
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


# ── AC6 — 5 failures lock recovery ────────────────────────────────────────────
# A lockout answers exactly as a bad code does, so it cannot tell a caller the
# email has an Account (#588); it shows only in the right code being refused.


@pytest.mark.asyncio
async def test_fifth_failed_attempt_locks_recovery(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    await _seed_failed_attempt(db_client, user_id, count=4)

    assert (await _redeem("wrong-code-yyyy")).status_code == 401
    assert (await _redeem(plaintext)).status_code == 401


@pytest.mark.asyncio
async def test_a_lockout_answers_exactly_like_a_bad_code(db_client) -> None:
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    bad = await _redeem("wrong-code-yyyy")
    await _seed_failed_attempt(db_client, user_id, count=4)

    locked = await _redeem(plaintext)

    assert (locked.status_code, locked.json()) == (bad.status_code, bad.json())


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


async def _redeem(code: str):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        return await c.post(
            "/auth/recovery/redeem",
            json={"email": "musashi@dojo.test", "code": code},
        )


@pytest.mark.asyncio
async def test_lockout_expires_after_fifteen_minutes(db_client) -> None:
    """Five failures lock recovery for 15 minutes, not forever (#580)."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    await _seed_failed_attempt(
        db_client,
        user_id,
        count=5,
        attempted_at=datetime.now(UTC) - timedelta(minutes=16),
    )

    assert (await _redeem(plaintext)).status_code == 200


@pytest.mark.asyncio
async def test_each_failure_past_the_lockout_doubles_it(db_client) -> None:
    """A sixth failure locks recovery for 30 minutes, not 15 (#580)."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    await _seed_failed_attempt(
        db_client,
        user_id,
        count=6,
        attempted_at=datetime.now(UTC) - timedelta(minutes=20),
    )

    assert (await _redeem(plaintext)).status_code == 401


@pytest.mark.asyncio
async def test_failures_older_than_a_day_stop_counting(db_client) -> None:
    """Five day-old failures and one fresh one are one failure, not a sixth
    that locks for 30 minutes (#580)."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    await _seed_failed_attempt(
        db_client,
        user_id,
        count=5,
        attempted_at=datetime.now(UTC) - timedelta(hours=25),
    )
    await _seed_failed_attempt(db_client, user_id)

    assert (await _redeem(plaintext)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hours_ago", "expected"), [(15, 401), (17, 200)], ids=["inside", "past"]
)
async def test_the_doubling_stops_at_sixteen_hours(
    db_client, hours_ago, expected
) -> None:
    """Twelve failures would lock for 32 hours if each doubled the lockout;
    it stops doubling at 16 (#580)."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    plaintext = "abcd-efgh-ijkl"
    await _seed_recovery_code(db_client, user_id, plaintext)
    await _seed_failed_attempt(
        db_client,
        user_id,
        count=12,
        attempted_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )

    assert (await _redeem(plaintext)).status_code == expected


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
@pytest.mark.parametrize("status", ["archived", "suspended"])
async def test_a_member_barred_from_signing_in_cannot_redeem(db_client, status) -> None:
    """A valid code is no way round #484: 401, as for an unknown address,
    and the code stays unused."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, _TEST_EMAIL, user_id, membership_status=status)
    plaintext = "abcd-efgh-ijkl"
    code_id = await _seed_recovery_code(db_client, user_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem", json={"email": _TEST_EMAIL, "code": plaintext}
        )

    assert response.status_code == 401
    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(RecoveryCode, code_id)
    assert row is not None and row.used_at is None


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
    """After a successful redemption, 4 new failures do not lock recovery."""

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
        assert r.status_code == 401

    # Not locked: the success reset the count, so 4 failures are not 7.
    assert (await _redeem(plaintext2)).status_code == 200


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
async def test_clear_expired_ip_addresses_clears_every_accounts_aged_ips(
    db_client,
) -> None:
    """Aged rows lose their IP, recent ones keep it; the rows themselves stay
    (#434), with no recovery attempt needed to trigger it (#467)."""
    now = datetime.now(UTC)
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
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

        await _clear_expired_ip_addresses(db_client)

        others = await _attempts_for(db_client, other_id)
        assert [(a.ip_address, a.success) for a in others] == [(None, False)]
        mine = await _attempts_for(db_client, user_id)
        assert [a.ip_address for a in mine] == ["127.0.0.1"]
    finally:
        await _wipe_test_email(db_client, other_email)


async def _clear_expired_ip_addresses(engine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await SqlAttemptRepository(session).clear_expired_ip_addresses()


@pytest.mark.asyncio
async def test_startup_clears_aged_ip_addresses(db_client, monkeypatch) -> None:
    """A quiet instance still clears on every app start (#467)."""
    import app.main as main_module

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_failed_attempt(
        db_client, user_id, attempted_at=datetime.now(UTC) - timedelta(days=31)
    )
    monkeypatch.setattr(main_module, "engine", db_client)

    # pytest's login is the superuser, which the app rightly refuses (#453).
    async def _allow(conn) -> None:
        return None

    monkeypatch.setattr(main_module, "_refuse_superuser", _allow)

    await main_module._init_db()

    assert [a.ip_address for a in await _attempts_for(db_client, user_id)] == [None]


@pytest.mark.asyncio
async def test_cli_clears_aged_ip_addresses(db_client, database_url) -> None:
    """What kendo-ip-retention.service runs daily (#467)."""
    from typer.testing import CliRunner

    from app.cli import app as cli_app

    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_failed_attempt(
        db_client, user_id, attempted_at=datetime.now(UTC) - timedelta(days=31)
    )

    result = CliRunner().invoke(
        cli_app,
        ["clear-expired-ip-addresses"],
        env={"DATABASE_URL": database_url},
    )

    assert result.exit_code == 0, f"output={result.output!r} exc={result.exception}"
    assert [a.ip_address for a in await _attempts_for(db_client, user_id)] == [None]


# ── #588 — redeem does not reveal whether an email has an Account ─────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["x" * 73, "é" * 37], ids=["73-ascii", "74-utf8"])
async def test_code_over_72_bytes_is_a_422(db_client, code) -> None:
    """bcrypt reads at most 72 bytes; past that it raised and answered 500
    for a known email and 401 for an unknown one."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_recovery_code(db_client, user_id, "real-code-xxxx")

    assert (await _redeem(code)).status_code == 422


async def _seed_code_set(engine, user_id: str) -> None:
    """A full set of 8 codes, hashed at bcrypt cost 4 to keep tests short."""
    async with engine.begin() as conn:
        for index in range(8):
            await conn.execute(
                insert(RecoveryCode).values(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    code_hash=bcrypt.hashpw(
                        f"real-code-{index:04}".encode(), bcrypt.gensalt(4)
                    ).decode(),
                    set_id=str(uuid.uuid4()),
                    created_at=datetime.now(UTC),
                )
            )


@pytest.fixture
def cheap_bcrypt(monkeypatch):
    """The app hashes and pads at the cost 4 `_seed_code_set` uses."""
    from app.auth import recovery_service

    monkeypatch.setattr(recovery_service, "BCRYPT_ROUNDS", 4)


async def _bad_code_answer(monkeypatch, email: str) -> tuple[int, dict, int]:
    """(status, body, bcrypt comparisons) for a bad code sent for `email`."""
    comparisons = []
    checkpw = bcrypt.checkpw

    def counting(password: bytes, hashed: bytes) -> bool:
        comparisons.append(hashed)
        return checkpw(password, hashed)

    monkeypatch.setattr(bcrypt, "checkpw", counting)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem", json={"email": email, "code": "wrong-code-yyyy"}
        )
    monkeypatch.setattr(bcrypt, "checkpw", checkpw)
    return response.status_code, response.json(), len(comparisons)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no codes", "unknown", "barred", "locked out"])
async def test_every_failure_answers_and_costs_as_a_bad_code(
    db_client, cheap_bcrypt, monkeypatch, case
) -> None:
    """An unknown email answered 401 before any bcrypt, and a lockout 429: both
    told a caller whether the email had an Account (#588). Every failure now
    gets the answer a bad code gets, after as many bcrypt comparisons."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", user_id)
    await _seed_code_set(db_client, user_id)
    bad_code = await _bad_code_answer(monkeypatch, "musashi@dojo.test")

    email = "musashi@dojo.test"
    if case == "no codes":
        async with db_client.begin() as conn:
            await conn.execute(
                delete(RecoveryCode).where(RecoveryCode.user_id == user_id)
            )
    elif case == "unknown":
        email = "nobody@dojo.test"
    elif case == "barred":
        async with db_client.begin() as conn:
            await conn.execute(
                update(Member)
                .where(Member.email == "musashi@dojo.test")
                .values(membership_status="archived")
            )
    else:
        await _seed_failed_attempt(db_client, user_id, count=4)

    assert await _bad_code_answer(monkeypatch, email) == bad_code


@pytest.mark.asyncio
@pytest.mark.timing_sensitive
async def test_the_padding_costs_what_a_real_code_does(
    db_client, cheap_bcrypt, monkeypatch
) -> None:
    """An Account with no codes checks the dummy hash where one with a full
    set checks its own; neither may answer faster (#588). Unknown, barred and
    locked-out emails check the same dummy (the test above).

    Both are Accounts, so the database work matches and only bcrypt is
    measured. An unknown email does less database work than a known one --
    no lockout lookup, no failed attempt to write -- which this helper's 1ms
    budget would see; that is not bcrypt, and not what #588 closes.
    """
    monkeypatch.setattr(app.state.limiter, "enabled", False)
    full_id, empty_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", full_id)
    await _seed_code_set(db_client, full_id)
    await _seed_user(db_client, "kojiro@dojo.test", empty_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:

        async def timed(email: str) -> float:
            # Outside the timing: clear failures so neither is locked out.
            async with db_client.begin() as conn:
                await conn.execute(
                    delete(RecoveryAttempt).where(
                        RecoveryAttempt.user_id.in_([full_id, empty_id])
                    )
                )
            start = time.perf_counter()
            response = await c.post(
                "/auth/recovery/redeem",
                json={"email": email, "code": "wrong-code-yyyy"},
            )
            elapsed = time.perf_counter() - start
            assert response.status_code == 401
            return elapsed

        try:
            await assert_latency_converges_sampled(
                lambda: timed("musashi@dojo.test"),
                lambda: timed("kojiro@dojo.test"),
                label_a="full code set",
                label_b="no codes",
            )
        finally:
            await _wipe_test_email(db_client, "kojiro@dojo.test")


@pytest.mark.asyncio
@pytest.mark.timing_sensitive
@pytest.mark.parametrize("other", ["unknown email", "Account with no tokens"])
async def test_an_account_holding_admin_tokens_answers_as_fast_as(
    db_client, cheap_bcrypt, monkeypatch, other
) -> None:
    """The redeem floor hides what only some emails cost (#594). Against an
    unknown email: the lockout lookup, the codes and tokens read, the failed
    attempt written. Against an Account with none: the comparisons of tokens
    seeded past the one-live-token rule."""
    monkeypatch.setattr(app.state.limiter, "enabled", False)
    monkeypatch.setattr(config, "RECOVERY_REDEEM_MIN_DURATION_MS", 150)
    holder_id, other_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_user(db_client, "musashi@dojo.test", holder_id)
    await _seed_code_set(db_client, holder_id)
    async with db_client.begin() as conn:
        for _ in range(3):
            await conn.execute(
                insert(AdminRecoveryToken).values(
                    id=str(uuid.uuid4()),
                    user_id=holder_id,
                    token_hash=bcrypt.hashpw(
                        b"admin-token", bcrypt.gensalt(4)
                    ).decode(),
                    expires_at=datetime.now(UTC) + timedelta(minutes=60),
                    created_at=datetime.now(UTC),
                )
            )
    other_email = "nobody@dojo.test"
    if other == "Account with no tokens":
        other_email = "kojiro@dojo.test"
        await _seed_user(db_client, other_email, other_id)
        await _seed_code_set(db_client, other_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:

        async def timed(email: str) -> float:
            # Outside the timing: clear failures so neither is locked out.
            async with db_client.begin() as conn:
                await conn.execute(
                    delete(RecoveryAttempt).where(
                        RecoveryAttempt.user_id.in_([holder_id, other_id])
                    )
                )
            start = time.perf_counter()
            response = await c.post(
                "/auth/recovery/redeem",
                json={"email": email, "code": "wrong-code-yyyy"},
            )
            elapsed = time.perf_counter() - start
            assert response.status_code == 401
            return elapsed

        try:
            await assert_latency_converges_sampled(
                lambda: timed("musashi@dojo.test"),
                lambda: timed(other_email),
                label_a="Account holding admin tokens",
                label_b=other,
            )
        finally:
            await _wipe_test_email(db_client, "kojiro@dojo.test")
