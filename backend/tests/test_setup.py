"""Tests for the first-run setup endpoint (issue #38).

Acceptance criteria:
1. GET /setup returns 200 when the users table is empty, 404 otherwise.
2. (Frontend redirect — tested in e2e)
3. (Frontend redirect — tested in e2e)
4. Setup page presents passkey registration flow — begin/complete endpoints
   are reachable from the setup context.
5. After successful registration via setup, user is admin and a cookie is set.
6. Unit test: GET /setup returns 404 after the first user is created.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.db_models import User
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


# ── AC1: GET /setup availability ──────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_setup_returns_200_when_no_users(db_client) -> None:
    """GET /setup returns 200 when the users table is empty (fresh instance)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/setup")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_get_setup_returns_404_when_users_exist(db_client) -> None:
    """GET /setup returns 404 when at least one user already exists."""
    engine = db_client
    # Seed a user directly so the table is non-empty
    async with engine.begin() as conn:
        from sqlalchemy import insert

        await conn.execute(
            insert(User).values(
                id=str(uuid.uuid4()),
                email="existing@dojo.test",
                hashed_password="$2b$12$irrelevant",
                role="admin",
                is_active=True,
            )
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/setup")
    assert response.status_code == 404
    # Must be a deliberate "setup already done" 404, not a generic route-not-found
    assert response.json().get("detail") == "Setup already completed"


# ── AC6: Unit test — 404 after first user created ─────────────────────────────


@pytest.mark.anyio
async def test_get_setup_returns_404_after_first_user_registered(db_client) -> None:
    """GET /setup returns 404 once a user has been registered (AC6)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        # Fresh instance: setup should be available
        before = await c.get("/setup")
        assert before.status_code == 200

        # Register the first user (creates the first row in users)
        await c.post(
            "/auth/register/password",
            json={"email": "founder@dojo.test", "password": "Str0ng!Pass"},
        )

        # Now setup should be gone
        after = await c.get("/setup")
    assert after.status_code == 404


# ── AC4: Setup exposes passkey registration begin endpoint ────────────────────


@pytest.mark.anyio
async def test_setup_passkey_begin_returns_challenge_on_fresh_instance(
    db_client,
) -> None:
    """POST /setup/passkey/begin returns 200 with WebAuthn challenge on fresh instance."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/setup/passkey/begin",
            json={"email": "admin@dojo.test"},
        )
    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]


@pytest.mark.anyio
async def test_setup_passkey_begin_returns_404_when_populated(db_client) -> None:
    """POST /setup/passkey/begin returns 404 when instance already has users."""
    engine = db_client
    async with engine.begin() as conn:
        from sqlalchemy import insert

        await conn.execute(
            insert(User).values(
                id=str(uuid.uuid4()),
                email="alreadyhere@dojo.test",
                hashed_password="$2b$12$irrelevant",
                role="admin",
                is_active=True,
            )
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/setup/passkey/begin",
            json={"email": "newcomer@dojo.test"},
        )
    assert response.status_code == 404
    assert response.json().get("detail") == "Setup already completed"


# ── AC5: Successful registration via setup → admin + cookie ──────────────────


@pytest.mark.anyio
async def test_setup_passkey_complete_creates_admin_and_sets_cookie(db_client) -> None:
    """POST /setup/passkey/complete on a fresh instance registers an admin user
    and sets the access_token cookie (AC5)."""
    engine = db_client

    # Seed a user row with pending_challenge (simulates what /setup/passkey/begin did)
    user_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        from sqlalchemy import insert

        await conn.execute(
            insert(User).values(
                id=user_id,
                email="admin@dojo.test",
                hashed_password="",
                role="admin",  # setup flow must grant admin
                is_active=True,
                pending_challenge="dGVzdC1jaGFsbGVuZ2U",
                challenge_issued_at=datetime.now(UTC),
            )
        )

    mock_verified = MagicMock()
    mock_verified.credential_id = b"setup-credential-id"
    mock_verified.credential_public_key = b"setup-public-key"
    mock_verified.sign_count = 0

    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
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


@pytest.mark.anyio
async def test_setup_passkey_complete_returns_404_when_populated(db_client) -> None:
    """POST /setup/passkey/complete returns 404 when instance already has users (AC5 guard)."""
    engine = db_client

    # Two users: one pre-existing admin, one attempting setup
    existing_id = str(uuid.uuid4())
    pending_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        from sqlalchemy import insert

        await conn.execute(
            insert(User).values(
                id=existing_id,
                email="original@dojo.test",
                hashed_password="$2b$12$irrelevant",
                role="admin",
                is_active=True,
            )
        )
        await conn.execute(
            insert(User).values(
                id=pending_id,
                email="newcomer@dojo.test",
                hashed_password="",
                role="member",
                is_active=True,
                pending_challenge="dGVzdC1jaGFsbGVuZ2U",
                challenge_issued_at=datetime.now(UTC),
            )
        )

    mock_verified = MagicMock()
    mock_verified.credential_id = b"late-credential-id"
    mock_verified.credential_public_key = b"late-public-key"
    mock_verified.sign_count = 0

    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
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
