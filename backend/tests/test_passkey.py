"""Tests for passkey (WebAuthn) registration and login flows.

These tests import from app.auth.passkey modules that do not yet exist —
that is intentional: they are the red phase of the TDD cycle.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from app.auth.db_models import Account, PasskeyCredential
from app.main import app
from app.members.db_models import Member
from tests.account_support import seed_account


async def _claimed_instance_with_member(session, email: str) -> None:
    """Seed the state the email-addressed registration route once enrolled
    from: an already claimed instance (one PasskeyCredential row) and a Member
    for `email`. So a refusal here is the route's own (#472), not the
    unclaimed-instance gate's.
    """
    seed_user_id = str(uuid.uuid4())
    await seed_account(
        session,
        f"claimed-{seed_user_id}@dojo.test",
        user_id=seed_user_id,
        role="admin",
        is_active=True,
    )
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=seed_user_id,
            credential_id=uuid.uuid4().bytes,
            public_key=b"seeded-public-key",
            sign_count=0,
            created_at=datetime.now(UTC),
        )
    )
    await session.execute(
        insert(Member).values(
            id=str(uuid.uuid4()),
            email=email,
            first_name="Test",
            surname="Member",
            join_date="2024-01-01",
            membership_status="active",
            is_coach=False,
            is_first_aider=False,
        )
    )
    await session.flush()


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


# ── Register begin ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_passkey_begin_is_gone(db_client) -> None:
    """Invites only (#472): there is no anonymous ceremony to begin. A begin
    would have a browser create a credential that complete can never accept,
    and would overwrite a known Member's pending sign-in challenge."""
    await _claimed_instance_with_member(db_client, "musashi@dojo.test")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "musashi@dojo.test"},
        )
    assert response.status_code == 404


# ── Register complete ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_passkey_complete_refuses_a_never_enrolled_member(
    db_client,
) -> None:
    """Invites only (#472): the email-addressed ceremony enrols nobody, not even
    a Member who has never set up a passkey. Otherwise anyone who knew their
    address could enrol their own authenticator and sign in as them.

    Everything else is in order here (pending challenge, a credential that
    verifies), so the refusal is the route's, not the ceremony's."""
    session = db_client
    await _claimed_instance_with_member(session, "complete@dojo.test")

    user_id = str(uuid.uuid4())
    await seed_account(
        session,
        "complete@dojo.test",
        user_id=user_id,
        role="member",
        is_active=True,
        pending_challenge="dGVzdC1jaGFsbGVuZ2U",
        challenge_issued_at=datetime.now(UTC),
    )
    await session.flush()

    mock_verified = MagicMock()
    mock_verified.credential_id = b"test-credential-id"
    mock_verified.credential_public_key = b"test-public-key"
    mock_verified.sign_count = 0

    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/auth/register/passkey/complete",
                json={
                    "email": "complete@dojo.test",
                    "credential": {
                        "id": "dGVzdC1jcmVkZW50aWFsLWlk",
                        "rawId": "dGVzdC1jcmVkZW50aWFsLWlk",
                        "response": {
                            "clientDataJSON": "dGVzdA",
                            "attestationObject": "dGVzdA",
                        },
                        "type": "public-key",
                    },
                },
            )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication failed"}
    stored = await session.execute(
        select(PasskeyCredential).where(PasskeyCredential.user_id == user_id)
    )
    assert stored.first() is None


# ── Login begin ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_passkey_begin_returns_options(db_client) -> None:
    """POST /auth/login/passkey/begin with known email returns 200 with publicKey.challenge.

    The user is seeded with a direct insert: POST /auth/register/password was
    removed in #155 (passkey-only auth), so the old two-call setup silently
    404'd and left no user behind — making this test exercise the *decoy*
    response for an unknown email, identical to the test directly below it
    (#283). Asserting that the challenge was persisted on the user row is what
    distinguishes the real path from the decoy: _decoy_login_response writes
    nothing to the database.
    """
    session = db_client
    user_id = str(uuid.uuid4())
    await seed_account(
        session, "loginbegin@dojo.test", user_id=user_id, role="member", is_active=True
    )
    await session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/login/passkey/begin",
            json={"email": "loginbegin@dojo.test"},
        )
    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]
    challenge = body["publicKey"]["challenge"]
    assert isinstance(challenge, str)
    assert len(challenge) > 0

    stored = (
        await session.execute(select(Account).where(Account.id == user_id))
    ).scalar_one()
    assert stored.pending_challenge == challenge
    assert stored.challenge_issued_at is not None


@pytest.mark.asyncio
async def test_login_passkey_begin_unknown_email_returns_200_decoy(db_client) -> None:
    """POST /auth/login/passkey/begin with unknown email returns 200 with a
    decoy challenge (issue #239: 404 here was an email-enumeration oracle).
    See tests/test_passkey_enumeration.py for full enumeration-fix coverage.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/login/passkey/begin",
            json={"email": "nobody@dojo.test"},
        )
    assert response.status_code == 200


# ── Login complete ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_passkey_complete_sets_cookie(db_client) -> None:
    """POST /auth/login/passkey/complete verifies assertion, sets access_token cookie."""
    session = db_client

    # Seed user with a pending challenge and a stored credential
    user_id = str(uuid.uuid4())
    credential_id_bytes = b"stored-credential-id"
    credential_id_b64 = "c3RvcmVkLWNyZWRlbnRpYWwtaWQ"  # base64url

    await seed_account(
        session,
        "logincomp@dojo.test",
        user_id=user_id,
        role="member",
        is_active=True,
        pending_challenge="dGVzdC1sb2dpbi1jaGFsbGVuZ2U",
        challenge_issued_at=datetime.now(UTC),
    )
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_id=credential_id_bytes,
            public_key=b"stored-public-key",
            sign_count=0,
        )
    )
    await session.flush()

    mock_verified = MagicMock()
    mock_verified.credential_id = credential_id_bytes
    mock_verified.new_sign_count = 1

    with patch("webauthn.verify_authentication_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/auth/login/passkey/complete",
                json={
                    "email": "logincomp@dojo.test",
                    "credential": {
                        "id": credential_id_b64,
                        "rawId": credential_id_b64,
                        "response": {
                            "clientDataJSON": "dGVzdA",
                            "authenticatorData": "dGVzdA",
                            "signature": "dGVzdA",
                        },
                        "type": "public-key",
                    },
                },
            )

    assert response.status_code == 200
    assert response.json() == {"detail": "logged in"}
    assert "access_token" in response.cookies


# ── Smoke test: password login unbroken ───────────────────────────────────────


@pytest.mark.xfail(
    strict=False,
    reason="POST /auth/login/password removed in issue #155 (passkey-only auth)",
)
@pytest.mark.asyncio
async def test_password_login_still_works(db_client) -> None:
    """POST /auth/login/password still returns 200 after passkey code is added."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.post(
            "/auth/register/password",
            json={"email": "smoke@dojo.test", "password": "Str0ng!Pass"},
        )
        response = await c.post(
            "/auth/login/password",
            json={"email": "smoke@dojo.test", "password": "Str0ng!Pass"},
        )
    assert response.status_code == 200
