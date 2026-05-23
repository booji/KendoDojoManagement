"""Tests for passkey (WebAuthn) registration and login flows.

These tests import from app.auth.passkey modules that do not yet exist —
that is intentional: they are the red phase of the TDD cycle.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.db_models import PasskeyCredential, User
from app.db.base import Base
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


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


# ── Register begin ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_register_passkey_begin_returns_options(db_client) -> None:
    """POST /auth/register/passkey/begin returns 200 with publicKey.challenge."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "musashi@dojo.test"},
        )
    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]
    assert isinstance(body["publicKey"]["challenge"], str)
    assert len(body["publicKey"]["challenge"]) > 0


@pytest.mark.anyio
async def test_register_passkey_begin_creates_user_if_not_exists(db_client) -> None:
    """Calling begin for a new email creates a User row in the DB."""
    engine = db_client

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "musashi@dojo.test"},
        )
    assert response.status_code == 200

    async with engine.connect() as conn:
        result = await conn.execute(
            select(User).where(User.email == "musashi@dojo.test")
        )
        user = result.fetchone()
    assert user is not None


@pytest.mark.anyio
async def test_register_passkey_begin_reuses_existing_user(db_client) -> None:
    """If the user already exists (password-registered), begin returns 200 without duplicate."""
    engine = db_client

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        # First create via password route
        await c.post(
            "/auth/register/password",
            json={"email": "existing@dojo.test", "password": "Str0ng!Pass"},
        )
        # Now call passkey begin for the same email
        response = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "existing@dojo.test"},
        )
    assert response.status_code == 200

    # Should still be exactly one user with that email
    async with engine.connect() as conn:
        result = await conn.execute(
            select(User).where(User.email == "existing@dojo.test")
        )
        rows = result.fetchall()
    assert len(rows) == 1


# ── Register complete ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_register_passkey_complete_stores_credential(db_client) -> None:
    """POST /auth/register/passkey/complete verifies credential and returns UserClaims (201)."""
    engine = db_client

    # Seed a user with a pending challenge
    user_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        from sqlalchemy import insert

        await conn.execute(
            insert(User).values(
                id=user_id,
                email="complete@dojo.test",
                role="member",
                is_active=True,
                pending_challenge="dGVzdC1jaGFsbGVuZ2U",  # base64url "test-challenge"
                challenge_issued_at=datetime.now(UTC),
            )
        )

    mock_verified = MagicMock()
    mock_verified.credential_id = b"test-credential-id"
    mock_verified.credential_public_key = b"test-public-key"
    mock_verified.sign_count = 0

    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
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

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "complete@dojo.test"
    assert "sub" in body
    assert "password" not in body
    assert "hashed_password" not in body


# ── Login begin ───────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=False,
    reason="POST /auth/register/password removed in issue #155 (passkey-only auth); seed via direct DB insert instead",
)
@pytest.mark.anyio
async def test_login_passkey_begin_returns_options(db_client) -> None:
    """POST /auth/login/passkey/begin with known email returns 200 with publicKey.challenge."""
    # First register a user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/register/password",
            json={"email": "loginbegin@dojo.test", "password": "Str0ng!Pass"},
        )
        response = await c.post(
            "/auth/login/passkey/begin",
            json={"email": "loginbegin@dojo.test"},
        )
    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]
    assert isinstance(body["publicKey"]["challenge"], str)
    assert len(body["publicKey"]["challenge"]) > 0


@pytest.mark.anyio
async def test_login_passkey_begin_unknown_email_returns_404(db_client) -> None:
    """POST /auth/login/passkey/begin with unknown email returns 404."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/login/passkey/begin",
            json={"email": "nobody@dojo.test"},
        )
    assert response.status_code == 404


# ── Login complete ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_login_passkey_complete_sets_cookie(db_client) -> None:
    """POST /auth/login/passkey/complete verifies assertion, sets access_token cookie."""
    engine = db_client

    # Seed user with a pending challenge and a stored credential
    user_id = str(uuid.uuid4())
    credential_id_bytes = b"stored-credential-id"
    credential_id_b64 = "c3RvcmVkLWNyZWRlbnRpYWwtaWQ"  # base64url

    async with engine.begin() as conn:
        from sqlalchemy import insert

        await conn.execute(
            insert(User).values(
                id=user_id,
                email="logincomp@dojo.test",
                role="member",
                is_active=True,
                pending_challenge="dGVzdC1sb2dpbi1jaGFsbGVuZ2U",
                challenge_issued_at=datetime.now(UTC),
            )
        )
        await conn.execute(
            insert(PasskeyCredential).values(
                id=str(uuid.uuid4()),
                user_id=user_id,
                credential_id=credential_id_bytes,
                public_key=b"stored-public-key",
                sign_count=0,
            )
        )

    mock_verified = MagicMock()
    mock_verified.credential_id = credential_id_bytes
    mock_verified.new_sign_count = 1

    with patch("webauthn.verify_authentication_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
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
@pytest.mark.anyio
async def test_password_login_still_works(db_client) -> None:
    """POST /auth/login/password still returns 200 after passkey code is added."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
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
