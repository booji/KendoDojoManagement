"""Failing tests for issue #101 — Rate limiting & account lockout.

Acceptance criteria exercised:
  AC1.  slowapi present in requirements.txt
  AC2.  locked_until nullable datetime column on User model
  AC3.  app/auth/rate_limiter.py module exists with expected attributes
  AC4.  Rate limits applied to all 6 auth endpoints
  AC5.  N+1th request returns 429 with Retry-After header
  AC6.  After 10 consecutive per-account failures, account locked for AUTH_LOCKOUT_MINUTES
  AC7.  Locked account returns clear error (detail: "Account temporarily locked")
  AC8.  Lockout state persists in DB (locked_until on User row)
  AC9.  visitor_name >100 chars rejected with 422; exactly 100 chars accepted
  AC10. Unit: per-IP and per-account limits enforced independently
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.db_models import User
from app.db.base import Base
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_TARGET_EMAIL = "lockout@dojo.test"


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


async def _seed_user(
    engine,
    email: str,
    user_id: str,
    *,
    role: str = "member",
    hashed_pw: str | None = None,
) -> None:
    """Insert a user row into the test DB."""
    if hashed_pw is None:
        hashed_pw = bcrypt.hashpw(b"hunter2", bcrypt.gensalt()).decode()
    async with engine.begin() as conn:
        await conn.execute(
            insert(User).values(
                id=user_id,
                email=email,
                hashed_password=hashed_pw,
                role=role,
                is_active=True,
            )
        )


# ── AC1 — slowapi in requirements.txt ─────────────────────────────────────────


def test_slowapi_in_requirements() -> None:
    """slowapi must be present in backend/requirements.txt."""
    req_path = Path(__file__).parent.parent / "requirements.txt"
    content = req_path.read_text()
    assert "slowapi" in content, "slowapi not found in requirements.txt"


# ── AC2 — locked_until column on User model ───────────────────────────────────


def test_user_model_has_locked_until_field() -> None:
    """User SQLAlchemy model must have a locked_until column."""
    assert hasattr(User, "locked_until"), "User model missing locked_until field"


def test_user_locked_until_is_nullable() -> None:
    """locked_until must be nullable (no lockout by default)."""
    col = User.__table__.columns["locked_until"]
    assert col.nullable, "locked_until column must be nullable"


# ── AC3 — rate_limiter module exists ──────────────────────────────────────────


def test_rate_limiter_module_importable() -> None:
    """app.auth.rate_limiter must be importable — fails until file is created."""
    import app.auth.rate_limiter  # noqa: F401


def test_rate_limiter_has_limiter_instance() -> None:
    """rate_limiter module must expose a 'limiter' object (slowapi Limiter)."""
    from app.auth import rate_limiter  # red

    assert hasattr(rate_limiter, "limiter"), "rate_limiter module missing 'limiter'"


def test_rate_limiter_has_per_ip_limit() -> None:
    """rate_limiter module must expose PER_IP_LIMIT constant or decorator."""
    from app.auth import rate_limiter  # red

    assert hasattr(
        rate_limiter, "PER_IP_LIMIT"
    ), "rate_limiter module missing 'PER_IP_LIMIT'"


def test_rate_limiter_has_per_account_limit() -> None:
    """rate_limiter module must expose PER_ACCOUNT_LIMIT constant or decorator."""
    from app.auth import rate_limiter  # red

    assert hasattr(
        rate_limiter, "PER_ACCOUNT_LIMIT"
    ), "rate_limiter module missing 'PER_ACCOUNT_LIMIT'"


# ── AC5 — 429 with Retry-After on /auth/login/password ───────────────────────


@pytest.mark.anyio
async def test_login_password_returns_429_after_limit(db_client) -> None:
    """POST /auth/login/password returns 429 after exceeding per-IP rate limit."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, _TARGET_EMAIL, user_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        # Fire enough requests to hit the IP rate limit (expect limit <= 20/minute)
        last_response = None
        for _ in range(21):
            last_response = await c.post(
                "/auth/login/password",
                json={"email": _TARGET_EMAIL, "password": "wrong-password"},
            )
            if last_response.status_code == 429:
                break

    assert last_response is not None
    assert last_response.status_code == 429


@pytest.mark.anyio
async def test_login_password_429_has_retry_after_header(db_client) -> None:
    """429 response from /auth/login/password must include Retry-After header."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, _TARGET_EMAIL, user_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        last_response = None
        for _ in range(21):
            last_response = await c.post(
                "/auth/login/password",
                json={"email": _TARGET_EMAIL, "password": "wrong-password"},
            )
            if last_response.status_code == 429:
                break

    assert last_response is not None
    assert last_response.status_code == 429
    assert (
        "retry-after" in last_response.headers or "Retry-After" in last_response.headers
    )


@pytest.mark.anyio
async def test_passkey_begin_returns_429_after_limit(db_client) -> None:
    """POST /auth/login/passkey/begin returns 429 after exceeding per-IP rate limit."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        last_response = None
        for _ in range(21):
            last_response = await c.post(
                "/auth/login/passkey/begin",
                json={"email": "anyuser@dojo.test"},
            )
            if last_response.status_code == 429:
                break

    assert last_response is not None
    assert last_response.status_code == 429


# ── AC6 — Account lockout after 10 consecutive failures ──────────────────────


@pytest.mark.anyio
async def test_account_locked_after_10_consecutive_failures(db_client) -> None:
    """After 10 consecutive bad passwords, 11th attempt returns error about lockout."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, _TARGET_EMAIL, user_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(10):
            await c.post(
                "/auth/login/password",
                json={"email": _TARGET_EMAIL, "password": "wrong-password"},
            )

        response = await c.post(
            "/auth/login/password",
            json={"email": _TARGET_EMAIL, "password": "wrong-password"},
        )

    # Should be locked — either 423 Locked or 429 with lockout detail
    assert response.status_code in (423, 429)


# ── AC7 — Locked account returns clear "Account temporarily locked" error ─────


@pytest.mark.anyio
async def test_locked_account_returns_clear_error_message(db_client) -> None:
    """Locked account must return detail: 'Account temporarily locked'."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, _TARGET_EMAIL, user_id)

    # Pre-lock the account by setting locked_until in the future
    future = datetime.now(UTC) + timedelta(minutes=15)
    async with db_client.begin() as conn:
        from sqlalchemy import text

        await conn.execute(
            text("UPDATE users SET locked_until = :lu WHERE id = :uid"),
            {"lu": future.isoformat(), "uid": user_id},
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/login/password",
            json={"email": _TARGET_EMAIL, "password": "hunter2"},
        )

    assert response.status_code in (423, 429)
    body = response.json()
    assert "detail" in body
    assert (
        "locked" in body["detail"].lower()
    ), f"Expected 'locked' in detail, got: {body['detail']!r}"


# ── AC8 — Lockout state persists in DB (locked_until on User row) ─────────────


@pytest.mark.anyio
async def test_lockout_sets_locked_until_on_user_row(db_client) -> None:
    """10 consecutive failures must write locked_until to the users table."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, _TARGET_EMAIL, user_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(10):
            await c.post(
                "/auth/login/password",
                json={"email": _TARGET_EMAIL, "password": "wrong-password"},
            )

    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()

    assert (
        user.locked_until is not None
    ), "locked_until must be set on user row after 10 consecutive failures"


@pytest.mark.anyio
async def test_locked_until_is_in_future_after_lockout(db_client) -> None:
    """locked_until must be set to a future timestamp (default 15 min)."""
    user_id = str(uuid.uuid4())
    await _seed_user(db_client, _TARGET_EMAIL, user_id)

    before = datetime.now(UTC)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(10):
            await c.post(
                "/auth/login/password",
                json={"email": _TARGET_EMAIL, "password": "wrong-password"},
            )

    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()

    assert user.locked_until is not None
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)

    assert locked_until > before, "locked_until must be in the future"


# ── AC9 — visitor_name validation (>100 chars → 422) ─────────────────────────


def test_add_visitor_request_rejects_name_over_100_chars() -> None:
    """AddVisitorRequest must reject visitor_name longer than 100 characters."""
    from pydantic import ValidationError

    from app.attendance.models import AddVisitorRequest

    long_name = "A" * 101
    with pytest.raises(ValidationError):
        AddVisitorRequest(visitor_name=long_name)


def test_add_visitor_request_accepts_name_exactly_100_chars() -> None:
    """AddVisitorRequest must accept visitor_name of exactly 100 characters."""
    from app.attendance.models import AddVisitorRequest

    exact_name = "B" * 100
    req = AddVisitorRequest(visitor_name=exact_name)
    assert req.visitor_name == exact_name


@pytest.mark.anyio
async def test_add_visitor_endpoint_returns_422_for_long_name(db_client) -> None:
    """POST /sessions/{id}/visitors with visitor_name >100 chars returns 422."""
    from app.auth.guards import REQUIRE_ADMIN
    from app.auth.models import UserClaims

    session_id = str(uuid.uuid4())
    claims = UserClaims(
        sub=str(uuid.uuid4()), email="m@dojo.test", role="admin", is_active=True
    )
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session_id}/visitors",
            json={"visitor_name": "X" * 101},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_add_visitor_endpoint_accepts_name_exactly_100_chars(db_client) -> None:
    """POST /sessions/{id}/visitors with visitor_name of exactly 100 chars passes validation."""
    from app.attendance.dependencies import get_attendance_repo
    from app.auth.guards import REQUIRE_MEMBER
    from app.auth.models import UserClaims

    session_id = str(uuid.uuid4())
    claims = UserClaims(
        sub=str(uuid.uuid4()), email="m@dojo.test", role="member", is_active=True
    )
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: claims

    class _StubAttendanceRepo:
        async def add_visitor(self, session_id, visitor_name, recorded_by):
            return {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "visitor_name": visitor_name,
                "checked_in_at": datetime.now(UTC).isoformat(),
                "recorded_by": recorded_by,
            }

    app.dependency_overrides[get_attendance_repo] = lambda: _StubAttendanceRepo()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session_id}/visitors",
            json={"visitor_name": "Y" * 100},
        )

    # Must NOT be 422 — validation passes for exactly 100 chars
    assert response.status_code != 422


# ── AC10 — Per-IP and per-account limits enforced independently ───────────────


def test_per_ip_limit_config_exists() -> None:
    """rate_limiter module must define a per-IP limit string (e.g. '10/minute')."""
    from app.auth import rate_limiter  # red

    limit = getattr(rate_limiter, "PER_IP_LIMIT", None)
    assert limit is not None
    assert isinstance(limit, str)
    assert "/" in limit, f"PER_IP_LIMIT should look like '10/minute', got: {limit!r}"


def test_per_account_limit_config_exists() -> None:
    """rate_limiter module must define a per-account limit string."""
    from app.auth import rate_limiter  # red

    limit = getattr(rate_limiter, "PER_ACCOUNT_LIMIT", None)
    assert limit is not None
    assert isinstance(limit, str)
    assert (
        "/" in limit
    ), f"PER_ACCOUNT_LIMIT should look like '10/minute', got: {limit!r}"
