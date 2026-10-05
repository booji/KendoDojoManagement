"""Issue #443 — passkey registration cannot attach a credential to someone
else's Account.

The unauthenticated ceremony (/auth/register/passkey/*) identifies the Account
by a submitted email, so it may only establish an Account's FIRST credential,
as an invite does. Adding another passkey goes through
/auth/passkeys/register/*, which takes the Account from the caller's session
cookie or recovery token, never from the request body.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, insert, select, update

from app.auth.db_models import Account, PasskeyCredential, RecoveryCode
from app.auth.models import AccountClaims
from app.main import app
from tests.account_support import seed_account
from tests.auth_support import sign_in

_CREDENTIAL = {
    "id": "bmV3LWNyZWQ",
    "rawId": "bmV3LWNyZWQ",
    "response": {"clientDataJSON": "dGVzdA", "attestationObject": "dGVzdA"},
    "type": "public-key",
}


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


async def _seed_account_with_passkey(session, email: str, role: str = "member") -> str:
    """An Account that already has a passkey, with a registration challenge
    pending (as /auth/register/passkey/begin would leave it)."""
    user_id = str(uuid.uuid4())
    await seed_account(
        session,
        email,
        user_id=user_id,
        role=role,
        is_active=True,
        pending_challenge="dGVzdC1jaGFsbGVuZ2U",
        challenge_issued_at=datetime.now(UTC),
    )
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_id=uuid.uuid4().bytes,
            public_key=b"owner-public-key",
            sign_count=0,
        )
    )
    await session.flush()
    return user_id


async def _passkey_count(session, user_id: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(PasskeyCredential)
        .where(PasskeyCredential.user_id == user_id)
    )
    return result.scalar_one()


@contextmanager
def _authenticator_says_yes():
    verified = MagicMock()
    verified.credential_id = uuid.uuid4().bytes
    verified.credential_public_key = b"new-public-key"
    verified.sign_count = 0
    verified.aaguid = None
    with patch("webauthn.verify_registration_response", return_value=verified):
        yield


def _client(**kwargs) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api", **kwargs
    )


async def test_unauthenticated_registration_cannot_add_to_an_account_with_a_passkey(
    db_client,
) -> None:
    email = "victim-admin@dojo.test"
    user_id = await _seed_account_with_passkey(db_client, email, role="admin")

    with _authenticator_says_yes():
        async with _client() as c:
            response = await c.post(
                "/auth/register/passkey/complete",
                json={"email": email, "credential": _CREDENTIAL},
            )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication failed"}
    assert await _passkey_count(db_client, user_id) == 1


def _claims(user_id: str, email: str) -> AccountClaims:
    return AccountClaims(sub=user_id, email=email, role="member", is_active=True)


def _session_cookie(user_id: str, email: str) -> dict[str, str]:
    return {"access_token": sign_in(_claims(user_id, email))}


def _recovery_token(user_id: str, email: str) -> str:
    return sign_in(_claims(user_id, email), kind="recovery")


async def _add_passkey(**auth) -> tuple[int, int]:
    """Run the authenticated ceremony with `auth` (cookies/headers for the
    client); the begin and complete status codes."""
    async with _client(**auth) as c:
        begin = await c.post("/auth/passkeys/register/begin")
        with _authenticator_says_yes():
            complete = await c.post(
                "/auth/passkeys/register/complete", json={"credential": _CREDENTIAL}
            )
    return begin.status_code, complete.status_code


async def test_a_signed_in_member_adds_a_second_passkey(db_client) -> None:
    email = "owner@dojo.test"
    user_id = await _seed_account_with_passkey(db_client, email)

    async with _client(cookies=_session_cookie(user_id, email)) as c:
        begin = await c.post("/auth/passkeys/register/begin")
        assert begin.status_code == 200
        assert "publicKey" in begin.json()
        with _authenticator_says_yes():
            complete = await c.post(
                "/auth/passkeys/register/complete", json={"credential": _CREDENTIAL}
            )

    assert complete.status_code == 201
    assert complete.json()["show_nudge"] is False
    assert complete.json()["sub"] == user_id
    assert await _passkey_count(db_client, user_id) == 2


async def test_a_recovery_token_adds_a_passkey(db_client) -> None:
    """After redeeming a recovery code the Member enrols a new passkey; the
    recovery token, sent as a Bearer header, is what names their Account."""
    email = "lost-device@dojo.test"
    user_id = await _seed_account_with_passkey(db_client, email)
    token = _recovery_token(user_id, email)

    statuses = await _add_passkey(headers={"Authorization": f"Bearer {token}"})

    assert statuses == (200, 201)
    assert await _passkey_count(db_client, user_id) == 2


async def test_a_recovery_token_enrols_only_one_passkey(db_client) -> None:
    """Single use: the recovery Auth Session ends with the passkey it enrolled."""
    email = "lost-device@dojo.test"
    user_id = await _seed_account_with_passkey(db_client, email)
    bearer = {"Authorization": f"Bearer {_recovery_token(user_id, email)}"}
    assert await _add_passkey(headers=bearer) == (200, 201)

    assert await _add_passkey(headers=bearer) == (401, 401)
    assert await _passkey_count(db_client, user_id) == 2


@pytest.mark.parametrize(
    "auth",
    [
        pytest.param(lambda uid, email: {}, id="nothing"),
        pytest.param(
            lambda uid, email: {"cookies": {"access_token": "not-a-jwt"}},
            id="garbage-cookie",
        ),
        pytest.param(
            lambda uid, email: {
                "cookies": {"access_token": _recovery_token(uid, email)}
            },
            id="recovery-token-as-cookie",
        ),
        pytest.param(
            lambda uid, email: {
                "headers": {
                    "Authorization": "Bearer "
                    + _session_cookie(uid, email)["access_token"]
                }
            },
            id="session-token-as-bearer",
        ),
    ],
)
async def test_adding_a_passkey_needs_the_callers_own_session(db_client, auth) -> None:
    email = "owner@dojo.test"
    user_id = await _seed_account_with_passkey(db_client, email)

    statuses = await _add_passkey(**auth(user_id, email))

    assert statuses == (401, 401)
    assert await _passkey_count(db_client, user_id) == 1


async def test_a_deactivated_account_cannot_add_a_passkey(db_client) -> None:
    email = "left@dojo.test"
    user_id = await _seed_account_with_passkey(db_client, email)
    token = _recovery_token(user_id, email)
    await db_client.execute(
        update(Account).where(Account.id == user_id).values(is_active=False)
    )

    statuses = await _add_passkey(headers={"Authorization": f"Bearer {token}"})

    assert statuses == (401, 401)
    assert await _passkey_count(db_client, user_id) == 1


async def test_an_account_that_deleted_its_last_passkey_is_not_open_again(
    db_client,
) -> None:
    """A Member may delete their only passkey while they hold recovery codes,
    leaving the Account with none. It is still somebody's Account: the
    email-addressed ceremony must not treat it as never enrolled."""
    # A claimed instance: with no passkey anywhere the bootstrap gate would
    # refuse on its own and hide whether this rule holds.
    await _seed_account_with_passkey(db_client, "someone-else@dojo.test")
    email = "codes-only@dojo.test"
    user_id = await _seed_account_with_passkey(db_client, email, role="admin")
    await db_client.execute(
        delete(PasskeyCredential).where(PasskeyCredential.user_id == user_id)
    )
    await db_client.execute(
        insert(RecoveryCode).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            code_hash="hash",
            set_id=str(uuid.uuid4()),
            created_at=datetime.now(UTC),
        )
    )

    with _authenticator_says_yes():
        async with _client() as c:
            response = await c.post(
                "/auth/register/passkey/complete",
                json={"email": email, "credential": _CREDENTIAL},
            )

    assert response.status_code == 401
    assert await _passkey_count(db_client, user_id) == 0
