"""Failing tests for issue #42 — Admin-issued recovery tokens.

Uses DB-backed integration tests against the shared PostgreSQL test database
(via the `database_url` fixture, real commits, own NullPool engine) matching
the pattern from test_recovery_redemption.py. This file's `db_client`
fixture is local, not the savepoint-scoped one in conftest.py, because these
tests need real cross-request commits (multiple HTTP requests each opening
their own session via get_uow).

Acceptance criteria exercised:
  AC1. admin_recovery_tokens table exists with correct fields
  AC2. POST /auth/recovery/admin-token (admin only) generates token, stores hash, returns plaintext
  AC3. POST /auth/recovery/redeem accepts admin tokens; expired/used tokens rejected
  AC6. 5-attempt lockout applies to admin token redemption
  AC7. Unit: valid redeems+marked used; expired rejected; used rejected; non-admin blocked
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.db_models import Account
from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app
from tests.account_support import seed_account, seed_member
from tests.e2e_support import leaves_members_as_found

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="admin@dojo.test", role="admin")
_MEMBER = AccountClaims(sub=str(uuid.uuid4()), email="member@dojo.test", role="member")
_TARGET_USER_ID = str(uuid.uuid4())
_TARGET_EMAIL = "target@dojo.test"

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
    # Real commits: remove what each test seeded, or its Admin Accounts would
    # claim the instance for test_setup.py (#589).
    with leaves_members_as_found():
        yield engine
    await engine.dispose()


async def _seed_user(engine, user_id: str, *, role: str = "member") -> str:
    """Insert a user row into the test DB. Returns the email used."""
    email = f"{user_id}@dojo.test"
    async with engine.begin() as conn:
        await seed_account(conn, email, user_id=user_id, role=role)
    return email


async def _member_of(engine, account_id: str) -> str:
    """The id of the Member an Account belongs to."""
    async with engine.connect() as conn:
        result = await conn.execute(
            select(Account.member_id).where(Account.id == account_id)
        )
    return result.scalar_one()


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
    from app.auth.db_models import AdminRecoveryToken  # red — model doesn't exist yet

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


def test_admin_recovery_token_model_exists() -> None:
    """AdminRecoveryToken model must exist in db_models."""
    from app.auth.db_models import AdminRecoveryToken  # red

    assert AdminRecoveryToken is not None


def test_admin_recovery_token_has_id_field() -> None:
    from app.auth.db_models import AdminRecoveryToken  # red

    assert hasattr(AdminRecoveryToken, "id")


def test_admin_recovery_token_has_user_id_field() -> None:
    from app.auth.db_models import AdminRecoveryToken  # red

    assert hasattr(AdminRecoveryToken, "user_id")


def test_admin_recovery_token_has_created_by_id_field() -> None:
    """created_by_id is a nullable FK — admin who issued the token."""
    from app.auth.db_models import AdminRecoveryToken  # red

    assert hasattr(AdminRecoveryToken, "created_by_id")


def test_admin_recovery_token_has_token_hash_field() -> None:
    from app.auth.db_models import AdminRecoveryToken  # red

    assert hasattr(AdminRecoveryToken, "token_hash")


def test_admin_recovery_token_has_expires_at_field() -> None:
    from app.auth.db_models import AdminRecoveryToken  # red

    assert hasattr(AdminRecoveryToken, "expires_at")


def test_admin_recovery_token_has_used_at_field() -> None:
    """used_at is nullable — None means the token has not been redeemed yet."""
    from app.auth.db_models import AdminRecoveryToken  # red

    assert hasattr(AdminRecoveryToken, "used_at")


def test_admin_recovery_token_has_created_at_field() -> None:
    from app.auth.db_models import AdminRecoveryToken  # red

    assert hasattr(AdminRecoveryToken, "created_at")


# ── AC2 — POST /auth/recovery/admin-token ─────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_can_generate_token_for_user(db_client) -> None:
    """POST /auth/recovery/admin-token (admin) returns plaintext token."""
    admin_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    await _seed_user(db_client, admin_id, role="admin")
    await _seed_user(db_client, target_id)

    claims = AccountClaims(sub=admin_id, email="admin@dojo.test", role="admin")
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/admin-token",
            json={"member_id": await _member_of(db_client, target_id)},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_token_response_contains_plaintext_token(db_client) -> None:
    """Response body includes the plaintext token field."""
    admin_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    await _seed_user(db_client, admin_id, role="admin")
    await _seed_user(db_client, target_id)

    claims = AccountClaims(sub=admin_id, email="admin@dojo.test", role="admin")
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/admin-token",
            json={"member_id": await _member_of(db_client, target_id)},
        )

    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert isinstance(body["token"], str)
    assert len(body["token"]) > 8


@pytest.mark.asyncio
async def test_admin_token_stored_as_hash_not_plaintext(db_client) -> None:
    """Plaintext token must NOT be stored; only bcrypt hash is persisted."""
    from app.auth.db_models import AdminRecoveryToken  # red

    admin_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    await _seed_user(db_client, admin_id, role="admin")
    await _seed_user(db_client, target_id)

    claims = AccountClaims(sub=admin_id, email="admin@dojo.test", role="admin")
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/admin-token",
            json={"member_id": await _member_of(db_client, target_id)},
        )

    assert response.status_code == 200
    plaintext = response.json()["token"]

    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(AdminRecoveryToken).where(AdminRecoveryToken.user_id == target_id)
        )
        row = result.scalar_one()

    assert row.token_hash != plaintext
    assert row.token_hash.startswith("$2")  # bcrypt prefix


@pytest.mark.asyncio
async def test_admin_token_expires_in_60_minutes(db_client) -> None:
    """Generated admin token has an expiry approximately 60 minutes in the future."""
    from app.auth.db_models import AdminRecoveryToken  # red

    admin_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    await _seed_user(db_client, admin_id, role="admin")
    await _seed_user(db_client, target_id)

    claims = AccountClaims(sub=admin_id, email="admin@dojo.test", role="admin")
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims

    before = datetime.now(UTC)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/admin-token",
            json={"member_id": await _member_of(db_client, target_id)},
        )
    after = datetime.now(UTC)

    assert response.status_code == 200

    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(AdminRecoveryToken).where(AdminRecoveryToken.user_id == target_id)
        )
        row = result.scalar_one()

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    delta_before = expires_at - before
    delta_after = expires_at - after
    assert timedelta(minutes=59) < delta_before < timedelta(minutes=61)
    assert delta_after > timedelta(minutes=0)


async def test_non_admin_cannot_generate_admin_token() -> None:
    """POST /auth/recovery/admin-token returns 403 for a member-role token."""
    from tests.auth_support import sign_in

    member_claims = AccountClaims(
        sub=str(uuid.uuid4()), email="m@dojo.test", role="member"
    )
    token = sign_in(member_claims)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api",
        cookies={"access_token": token},
    ) as c:
        response = await c.post(
            "/auth/recovery/admin-token",
            json={"member_id": str(uuid.uuid4())},
        )

    assert response.status_code == 403


async def test_unauthenticated_cannot_generate_admin_token() -> None:
    """POST /auth/recovery/admin-token returns 401 with no token."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/admin-token",
            json={"member_id": str(uuid.uuid4())},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_token_returns_404_for_unknown_user(db_client) -> None:
    """POST /auth/recovery/admin-token returns 404 when member_id doesn't exist."""
    admin_id = str(uuid.uuid4())
    await _seed_user(db_client, admin_id, role="admin")

    claims = AccountClaims(sub=admin_id, email="admin@dojo.test", role="admin")
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/admin-token",
            json={"member_id": str(uuid.uuid4())},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_token_returns_404_for_a_member_with_no_account(db_client) -> None:
    """A Member who never registered has nothing to recover (#445)."""
    from app.auth.db_models import AdminRecoveryToken

    admin_id = str(uuid.uuid4())
    await _seed_user(db_client, admin_id, role="admin")
    async with db_client.begin() as conn:
        member_id = await seed_member(conn, f"{uuid.uuid4()}@dojo.test")

    claims = AccountClaims(sub=admin_id, email="admin@dojo.test", role="admin")
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/admin-token", json={"member_id": member_id}
        )

    assert response.status_code == 404
    assert "no account" in response.json()["detail"]
    async with db_client.connect() as conn:
        rows = await conn.execute(
            select(AdminRecoveryToken).where(
                AdminRecoveryToken.created_by_id == admin_id
            )
        )
    assert rows.all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("membership_status", ["archived", "suspended"])
async def test_admin_token_refused_for_a_member_barred_from_signing_in(
    db_client, membership_status
) -> None:
    """Redemption refuses an archived or suspended Member (#484), so a token
    for one could never be used; refuse it up front rather than hand the
    admin a dud."""
    from app.auth.db_models import AdminRecoveryToken

    admin_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    await _seed_user(db_client, admin_id, role="admin")
    async with db_client.begin() as conn:
        await seed_account(
            conn,
            f"{target_id}@dojo.test",
            user_id=target_id,
            membership_status=membership_status,
        )
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: AccountClaims(
        sub=admin_id, email="admin@dojo.test", role="admin"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/admin-token",
            json={"member_id": await _member_of(db_client, target_id)},
        )

    assert response.status_code == 409
    assert "archived or suspended" in response.json()["detail"]
    async with db_client.connect() as conn:
        rows = await conn.execute(
            select(AdminRecoveryToken).where(AdminRecoveryToken.user_id == target_id)
        )
    assert rows.all() == []


@pytest.mark.asyncio
async def test_admin_token_missing_member_id_returns_422(db_client) -> None:
    """POST /auth/recovery/admin-token returns 422 when member_id is absent."""
    admin_id = str(uuid.uuid4())
    await _seed_user(db_client, admin_id, role="admin")

    claims = AccountClaims(sub=admin_id, email="admin@dojo.test", role="admin")
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/auth/recovery/admin-token", json={})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_admin_token_malformed_member_id_returns_422(db_client) -> None:
    admin_id = str(uuid.uuid4())
    await _seed_user(db_client, admin_id, role="admin")
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: AccountClaims(
        sub=admin_id, email="admin@dojo.test", role="admin"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/admin-token", json={"member_id": "not-a-uuid"}
        )

    assert response.status_code == 422


# ── AC3 — POST /auth/recovery/redeem accepts admin tokens ─────────────────────


@pytest.mark.asyncio
async def test_redeem_valid_admin_token_returns_200(db_client) -> None:
    """POST /auth/recovery/redeem succeeds with a valid admin-issued token."""
    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok1-abcd"
    await _seed_admin_token(db_client, target_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": plaintext},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_redeem_valid_admin_token_returns_access_token(db_client) -> None:
    """Redeeming a valid admin token returns a JWT access token."""
    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok1-abcd"
    await _seed_admin_token(db_client, target_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": plaintext},
        )

    body = response.json()
    assert "access_token" in body


@pytest.mark.asyncio
async def test_redeem_valid_admin_token_marks_it_used(db_client) -> None:
    """After redemption, used_at is set on the admin token row."""
    from app.auth.db_models import AdminRecoveryToken  # red

    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok1-abcd"
    token_id = await _seed_admin_token(db_client, target_id, plaintext)

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


@pytest.mark.asyncio
async def test_redeem_expired_admin_token_returns_401(db_client) -> None:
    """POST /auth/recovery/redeem rejects an expired admin token with 401."""
    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok1-abcd"
    expired = datetime.now(UTC) - timedelta(minutes=1)
    await _seed_admin_token(db_client, target_id, plaintext, expires_at=expired)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": plaintext},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_redeem_used_admin_token_returns_401(db_client) -> None:
    """POST /auth/recovery/redeem rejects an already-used admin token with 401."""
    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok1-abcd"
    await _seed_admin_token(db_client, target_id, plaintext, used=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": plaintext},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_redeem_admin_token_twice_second_is_401(db_client) -> None:
    """Redeeming the same admin token twice: second attempt returns 401."""
    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok1-abcd"
    await _seed_admin_token(db_client, target_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        r1 = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": plaintext},
        )
        r2 = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": plaintext},
        )

    assert r1.status_code == 200
    assert r2.status_code == 401


# ── AC6 — 5-attempt lockout applies to admin token redemption ─────────────────


@pytest.mark.asyncio
async def test_fifth_failed_admin_token_attempt_returns_429(db_client) -> None:
    """After 4 prior failures, a 5th bad attempt at admin token redeem returns 429."""
    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok1-abcd"
    await _seed_admin_token(db_client, target_id, plaintext)
    await _seed_failed_attempt(db_client, target_id, count=4)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": "wrong-token-xxxx"},
        )

    assert response.status_code == 429


@pytest.mark.asyncio
async def test_issuing_an_admin_token_lifts_a_recovery_lockout(db_client) -> None:
    """Five failures lock recovery, but a token the admin issues afterwards
    still redeems: issuing it clears the Account's failures (#580)."""
    admin_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    await _seed_user(db_client, admin_id, role="admin")
    target_email = await _seed_user(db_client, target_id)
    await _seed_failed_attempt(db_client, target_id, count=5)
    claims = AccountClaims(sub=admin_id, email="admin@dojo.test", role="admin")
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        issued = await c.post(
            "/auth/recovery/admin-token",
            json={"member_id": await _member_of(db_client, target_id)},
        )
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": issued.json()["token"]},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_four_failures_still_allows_admin_token_attempt(db_client) -> None:
    """3 prior failures: 4th attempt with valid admin token should succeed."""
    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok1-abcd"
    await _seed_admin_token(db_client, target_id, plaintext)
    await _seed_failed_attempt(db_client, target_id, count=3)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": plaintext},
        )

    assert response.status_code == 200


# ── AC7 — Unit coverage ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_admin_token_redeems_and_is_marked_used(db_client) -> None:
    """Unit: valid admin token → 200 + token row has used_at set."""
    from app.auth.db_models import AdminRecoveryToken  # red

    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok2-efgh"
    token_id = await _seed_admin_token(db_client, target_id, plaintext)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        r = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": plaintext},
        )

    assert r.status_code == 200
    factory = async_sessionmaker(db_client, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(AdminRecoveryToken, token_id)
    assert row.used_at is not None


@pytest.mark.asyncio
async def test_expired_admin_token_is_rejected(db_client) -> None:
    """Unit: expired admin token → 401."""
    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok2-efgh"
    expired = datetime.now(UTC) - timedelta(hours=2)
    await _seed_admin_token(db_client, target_id, plaintext, expires_at=expired)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        r = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": plaintext},
        )

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_used_admin_token_is_rejected(db_client) -> None:
    """Unit: already-used admin token → 401."""
    target_id = str(uuid.uuid4())
    target_email = await _seed_user(db_client, target_id)
    plaintext = "admn-tok2-efgh"
    await _seed_admin_token(db_client, target_id, plaintext, used=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        r = await c.post(
            "/auth/recovery/redeem",
            json={"email": target_email, "code": plaintext},
        )

    assert r.status_code == 401


async def test_non_admin_cannot_call_generate_endpoint() -> None:
    """Unit: member-role token → 403 on POST /auth/recovery/admin-token."""
    from tests.auth_support import sign_in

    member_claims = AccountClaims(
        sub=str(uuid.uuid4()), email="m@dojo.test", role="member"
    )
    token = sign_in(member_claims)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api",
        cookies={"access_token": token},
    ) as c:
        r = await c.post(
            "/auth/recovery/admin-token",
            json={"member_id": str(uuid.uuid4())},
        )

    assert r.status_code == 403
