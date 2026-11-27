"""Auth Sessions against PostgreSQL (#485): sign-in, revocation, the join.

Through the real routes, so the cookie a sign-in sets is the one the guard
later resolves. The cascades are the revocation for erasure and for passkey
removal, and only real foreign keys can show them working.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, insert, select, update

from app.auth.accounts import delete_account
from app.auth.db_models import Account, AuthSession, PasskeyCredential
from app.main import app
from app.members.db_models import Member
from tests.account_support import seed_account


@pytest.fixture(autouse=True)
def clear_overrides():
    # On entry too: an in-memory Auth Session fake another file left installed
    # (tests.auth_support.sign_in) would quietly stand in for PostgreSQL here.
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api")


async def _add_passkey(session, user_id: str, credential_id: bytes) -> str:
    passkey_id = str(uuid.uuid4())
    await session.execute(
        insert(PasskeyCredential).values(
            id=passkey_id,
            user_id=user_id,
            credential_id=credential_id,
            public_key=b"public-key",
            sign_count=0,
            created_at=datetime.now(UTC),
        )
    )
    return passkey_id


async def _sign_in(email: str, credential_id: bytes) -> str:
    """Sign in with a passkey and return the session cookie it set."""
    done = await _attempt_sign_in(email, credential_id)
    assert done.status_code == 200, done.text
    return done.cookies["access_token"]


async def _attempt_sign_in(email: str, credential_id: bytes):
    """The login ceremony's complete response, with a valid signature."""
    b64 = __import__("base64").urlsafe_b64encode(credential_id).decode().rstrip("=")
    async with _client() as c:
        begin = await c.post("/auth/login/passkey/begin", json={"email": email})
        assert begin.status_code == 200
        verified = MagicMock(credential_id=credential_id, new_sign_count=1)
        with patch("webauthn.verify_authentication_response", return_value=verified):
            done = await c.post(
                "/auth/login/passkey/complete",
                json={
                    "email": email,
                    "credential": {
                        "id": b64,
                        "rawId": b64,
                        "response": {
                            "clientDataJSON": "dGVzdA",
                            "authenticatorData": "dGVzdA",
                            "signature": "dGVzdA",
                        },
                        "type": "public-key",
                    },
                },
            )
    return done


async def _status(path: str, cookie: str, method: str = "GET") -> int:
    async with _client() as c:
        c.cookies.set("access_token", cookie)
        r = await c.request(method, path)
    return r.status_code


async def _member_with_two_passkeys(session, role: str = "member"):
    email = f"ken-{uuid.uuid4().hex[:6]}@dojo.test"
    user_id = await seed_account(session, email, role=role)
    first = await _add_passkey(session, user_id, b"phone-" + uuid.uuid4().bytes)
    second = await _add_passkey(session, user_id, b"laptop-" + uuid.uuid4().bytes)
    creds = {
        pid: (
            await session.execute(
                select(PasskeyCredential.credential_id).where(
                    PasskeyCredential.id == pid
                )
            )
        ).scalar_one()
        for pid in (first, second)
    }
    return email, user_id, (first, creds[first]), (second, creds[second])


async def test_signing_in_stores_only_the_hash_of_the_cookie(db_client) -> None:
    email, user_id, (_, phone), _ = await _member_with_two_passkeys(db_client)

    cookie = await _sign_in(email, phone)

    assert await _status("/auth/me", cookie) == 200
    hashes = (
        (
            await db_client.execute(
                select(AuthSession.token_hash).where(AuthSession.account_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(hashes) == 1 and cookie not in hashes


async def test_logout_ends_the_auth_session(db_client) -> None:
    email, _, (_, phone), _ = await _member_with_two_passkeys(db_client)
    cookie = await _sign_in(email, phone)

    assert await _status("/auth/logout", cookie, "POST") == 200

    assert await _status("/auth/me", cookie) == 401


async def test_removing_a_passkey_ends_only_its_auth_sessions(db_client) -> None:
    email, _, (phone_id, phone), (_, laptop) = await _member_with_two_passkeys(
        db_client
    )
    on_phone = await _sign_in(email, phone)
    on_laptop = await _sign_in(email, laptop)

    assert await _status(f"/auth/passkeys/{phone_id}", on_laptop, "DELETE") == 204

    assert await _status("/auth/me", on_phone) == 401
    assert await _status("/auth/me", on_laptop) == 200


async def test_deleting_the_account_deletes_its_auth_sessions(db_client) -> None:
    email, user_id, (_, phone), _ = await _member_with_two_passkeys(db_client)
    await _sign_in(email, phone)

    await delete_account(db_client, user_id)

    left = await db_client.execute(
        select(func.count())
        .select_from(AuthSession)
        .where(AuthSession.account_id == user_id)
    )
    assert left.scalar_one() == 0


async def test_a_role_change_bites_on_the_next_request(db_client) -> None:
    email, user_id, (_, phone), _ = await _member_with_two_passkeys(
        db_client, role="admin"
    )
    cookie = await _sign_in(email, phone)
    assert await _status("/auth/admin/invites", cookie) == 200

    await db_client.execute(
        update(Account).where(Account.id == user_id).values(role="member")
    )

    assert await _status("/auth/admin/invites", cookie) == 403


async def _set_membership_status(session, user_id: str, status: str) -> None:
    member_id = select(Account.member_id).where(Account.id == user_id)
    await session.execute(
        update(Member)
        .where(Member.id == member_id.scalar_subquery())
        .values(membership_status=status)
    )


@pytest.mark.parametrize(
    ("status", "expected"), [("archived", 401), ("suspended", 401), ("inactive", 200)]
)
async def test_a_membership_status_change_bites_on_the_next_request(
    db_client, status: str, expected: int
) -> None:
    """Archiving or suspending a Member ends their live Auth Sessions with no
    revocation hook (#484): the guard reads the status on every request.
    401, as for no Auth Session at all, so the SPA routes to /login (#396)."""
    email, user_id, (_, phone), _ = await _member_with_two_passkeys(db_client)
    cookie = await _sign_in(email, phone)

    await _set_membership_status(db_client, user_id, status)

    assert await _status("/auth/me", cookie) == expected


@pytest.mark.parametrize(
    ("status", "expected"), [("archived", 403), ("suspended", 403), ("inactive", 200)]
)
async def test_sign_in_is_refused_by_membership_status(
    db_client, status: str, expected: int
) -> None:
    """403 only after the signature checks out, so an unproven caller cannot
    tell a barred Member from an unknown address (#484)."""
    email, user_id, (_, phone), _ = await _member_with_two_passkeys(db_client)
    await _set_membership_status(db_client, user_id, status)

    response = await _attempt_sign_in(email, phone)

    assert response.status_code == expected
    assert ("access_token" in response.cookies) == (expected == 200)


# ── Sign out everywhere (#487) ────────────────────────────────────────────────


async def test_signing_out_everywhere_deletes_every_row_of_the_account(
    db_client,
) -> None:
    """Recovery tokens included (ADR-0008): someone signing out everywhere
    because their Account is compromised must not leave an attacker's
    recovery token 15 minutes to enrol a passkey. Another Account's rows stay."""
    from app.auth.auth_session_repository import SqlAuthSessionRepository
    from app.auth.auth_sessions import start_auth_session

    email, user_id, (_, phone), _ = await _member_with_two_passkeys(db_client)
    other_email, other_id, (_, theirs), _ = await _member_with_two_passkeys(db_client)
    signed_in = await _sign_in(email, phone)
    await _sign_in(other_email, theirs)
    await start_auth_session(
        SqlAuthSessionRepository(db_client), user_id, kind="recovery"
    )

    assert await _status("/auth/sign-out-everywhere", signed_in, "POST") == 200

    owners = (await db_client.execute(select(AuthSession.account_id))).scalars().all()
    assert user_id not in owners
    assert other_id in owners


# ── Barring a Member deletes their Auth Sessions (#484) ───────────────────────


async def _put_status(member_id: str, status: str) -> int:
    from app.auth.guards import REQUIRE_ADMIN
    from app.auth.schemas import AccountClaims

    app.dependency_overrides[REQUIRE_ADMIN] = lambda: AccountClaims(
        sub="acting-admin", email="acting@dojo.test", role="admin"
    )
    try:
        async with _client() as c:
            r = await c.put(f"/members/{member_id}", json={"membership_status": status})
    finally:
        app.dependency_overrides.pop(REQUIRE_ADMIN)
    return r.status_code


@pytest.mark.parametrize("barred", ["archived", "suspended"])
async def test_reinstating_a_barred_member_does_not_revive_their_auth_sessions(
    db_client, barred: str
) -> None:
    """Barring deletes every row of the Account, recovery ones included, so the
    Admin reinstating the Member before those rows expire brings none back."""
    from app.auth.auth_session_repository import SqlAuthSessionRepository
    from app.auth.auth_sessions import start_auth_session

    email, user_id, (_, phone), _ = await _member_with_two_passkeys(db_client)
    cookie = await _sign_in(email, phone)
    await start_auth_session(
        SqlAuthSessionRepository(db_client), user_id, kind="recovery"
    )
    member_id = (
        await db_client.execute(select(Account.member_id).where(Account.id == user_id))
    ).scalar_one()

    assert await _put_status(member_id, barred) == 200
    assert await _put_status(member_id, "active") == 200

    assert await _status("/auth/me", cookie) == 401
    left = await db_client.execute(
        select(func.count())
        .select_from(AuthSession)
        .where(AuthSession.account_id == user_id)
    )
    assert left.scalar_one() == 0
