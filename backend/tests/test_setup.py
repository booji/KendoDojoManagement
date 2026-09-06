"""Tests for the first-run setup endpoint (issue #38) and passkey-only guard (issue #155).

Acceptance criteria:
1. GET /setup returns 200 when no fully-registered user exists, 404 otherwise.
2. (Frontend redirect — tested in e2e)
3. (Frontend redirect — tested in e2e)
4. Setup page presents passkey registration flow — begin/complete endpoints
   are reachable from the setup context.
5. After successful registration via setup, user is admin and a cookie is set.
6. Unit test: GET /setup returns 404 after the first user is created via passkey.
7. _has_registered_user returns False for a phantom user (no PasskeyCredential row),
   and True only once a PasskeyCredential row exists (AC12 of issue #155).
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from app.auth.db_models import PasskeyCredential, User
from app.main import app

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


# ── AC1: GET /setup availability ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_setup_returns_200_when_no_users(db_client) -> None:
    """GET /setup returns 200 when the users table is empty (fresh instance)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/setup")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_setup_returns_404_when_passkey_credential_exists(db_client) -> None:
    """GET /setup returns 404 when at least one PasskeyCredential row exists (AC7 issue #155)."""
    session = db_client
    user_id = str(uuid.uuid4())
    await session.execute(
        insert(User).values(
            id=user_id,
            email="existing@dojo.test",
            role="admin",
            is_active=True,
        )
    )
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_id=b"cred-id-bytes",
            public_key=b"pub-key-bytes",
            sign_count=0,
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/setup")
    assert response.status_code == 404
    assert response.json().get("detail") == "Setup already completed"


# ── AC12 of issue #155: _has_registered_user checks PasskeyCredential only ────


@pytest.mark.asyncio
async def test_get_setup_returns_200_for_phantom_user_without_credential(
    db_client,
) -> None:
    """GET /setup returns 200 when only a phantom user exists (no PasskeyCredential).

    A phantom user has no credentials — an abandoned begin ceremony.
    It must NOT count as a registered user (AC12 issue #155).
    """
    session = db_client
    await session.execute(
        insert(User).values(
            id=str(uuid.uuid4()),
            email="phantom@dojo.test",
            role="member",
            is_active=True,
            pending_challenge="dGVzdC1jaGFsbGVuZ2U",
            challenge_issued_at=datetime.now(UTC),
        )
    )
    await session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/setup")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_setup_returns_200_for_user_without_credential(
    db_client,
) -> None:
    """GET /setup returns 200 when a user row exists but has no PasskeyCredential.

    _has_registered_user checks only PasskeyCredential rows (AC12 issue #155).
    A user with no credential is a phantom/abandoned ceremony and must not block setup.
    """
    session = db_client
    await session.execute(
        insert(User).values(
            id=str(uuid.uuid4()),
            email="no-cred@dojo.test",
            role="admin",
            is_active=True,
        )
    )
    await session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/setup")
    assert response.status_code == 200


# ── AC6: Unit test — 404 after first user created ─────────────────────────────


@pytest.mark.asyncio
async def test_get_setup_returns_404_after_first_user_registered(db_client) -> None:
    """GET /setup returns 404 once a PasskeyCredential exists (AC6).

    The /auth/register/password route is gone (issue #155), so we seed
    a user + credential directly to simulate a completed passkey registration.
    """
    session = db_client

    # Fresh instance: setup should be available
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        before = await c.get("/setup")
    assert before.status_code == 200

    # Simulate a completed passkey registration (user + credential row)
    user_id = str(uuid.uuid4())
    await session.execute(
        insert(User).values(
            id=user_id,
            email="founder@dojo.test",
            role="admin",
            is_active=True,
        )
    )
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_id=b"founder-cred",
            public_key=b"founder-pubkey",
            sign_count=0,
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        after = await c.get("/setup")
    assert after.status_code == 404


# ── AC4: Setup exposes passkey registration begin endpoint ────────────────────


@pytest.mark.asyncio
async def test_setup_passkey_begin_returns_challenge_on_fresh_instance(
    db_client,
) -> None:
    """POST /setup/passkey/begin returns 200 with WebAuthn challenge on fresh instance."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/setup/passkey/begin",
            json={"email": "admin@dojo.test"},
        )
    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]


@pytest.mark.asyncio
async def test_setup_passkey_begin_returns_404_when_populated(db_client) -> None:
    """POST /setup/passkey/begin returns 404 when instance already has a PasskeyCredential."""
    session = db_client
    user_id = str(uuid.uuid4())
    await session.execute(
        insert(User).values(
            id=user_id,
            email="alreadyhere@dojo.test",
            role="admin",
            is_active=True,
        )
    )
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_id=b"already-cred",
            public_key=b"already-pubkey",
            sign_count=0,
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/setup/passkey/begin",
            json={"email": "newcomer@dojo.test"},
        )
    assert response.status_code == 404
    assert response.json().get("detail") == "Setup already completed"


# ── AC5: Successful registration via setup → admin + cookie ──────────────────


@pytest.mark.asyncio
async def test_setup_passkey_complete_creates_admin_and_sets_cookie(db_client) -> None:
    """POST /setup/passkey/complete on a fresh instance registers an admin user
    and sets the access_token cookie (AC5)."""
    session = db_client

    # Seed a user row with pending_challenge (simulates what /setup/passkey/begin did)
    user_id = str(uuid.uuid4())
    await session.execute(
        insert(User).values(
            id=user_id,
            email="admin@dojo.test",
            role="admin",  # setup flow must grant admin
            is_active=True,
            pending_challenge="dGVzdC1jaGFsbGVuZ2U",
            challenge_issued_at=datetime.now(UTC),
        )
    )
    await session.flush()

    mock_verified = MagicMock()
    mock_verified.credential_id = b"setup-credential-id"
    mock_verified.credential_public_key = b"setup-public-key"
    mock_verified.sign_count = 0

    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/setup/passkey/complete",
                json={
                    "email": "admin@dojo.test",
                    "credential": {
                        "id": "c2V0dXAtY3JlZGVudGlhbC1pZA",
                        "rawId": "c2V0dXAtY3JlZGVudGlhbC1pZA",
                        "response": {
                            "clientDataJSON": "dGVzdA",
                            "attestationObject": "dGVzdA",
                        },
                        "type": "public-key",
                    },
                },
            )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "admin@dojo.test"
    assert body["role"] == "admin"
    assert "access_token" in response.cookies


@pytest.mark.asyncio
async def test_setup_passkey_complete_returns_404_when_populated(db_client) -> None:
    """POST /setup/passkey/complete returns 404 when instance already has a
    PasskeyCredential (AC5 guard)."""
    session = db_client

    existing_id = str(uuid.uuid4())
    pending_id = str(uuid.uuid4())
    await session.execute(
        insert(User).values(
            id=existing_id,
            email="original@dojo.test",
            role="admin",
            is_active=True,
        )
    )
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=existing_id,
            credential_id=b"original-cred",
            public_key=b"original-pubkey",
            sign_count=0,
            created_at=datetime.now(UTC),
        )
    )
    await session.execute(
        insert(User).values(
            id=pending_id,
            email="newcomer@dojo.test",
            role="member",
            is_active=True,
            pending_challenge="dGVzdC1jaGFsbGVuZ2U",
            challenge_issued_at=datetime.now(UTC),
        )
    )
    await session.flush()

    mock_verified = MagicMock()
    mock_verified.credential_id = b"late-credential-id"
    mock_verified.credential_public_key = b"late-public-key"
    mock_verified.sign_count = 0

    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/setup/passkey/complete",
                json={
                    "email": "newcomer@dojo.test",
                    "credential": {
                        "id": "bGF0ZS1jcmVkZW50aWFsLWlk",
                        "rawId": "bGF0ZS1jcmVkZW50aWFsLWlk",
                        "response": {
                            "clientDataJSON": "dGVzdA",
                            "attestationObject": "dGVzdA",
                        },
                        "type": "public-key",
                    },
                },
            )

    assert response.status_code == 404
    assert response.json().get("detail") == "Setup already completed"
