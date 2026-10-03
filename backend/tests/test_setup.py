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
from sqlalchemy import insert, select

import app.config as config
from app.auth.db_models import PasskeyCredential, User
from app.main import app
from app.members.db_models import Member
from tests.account_support import seed_account

# The claim gate (ADR-0003, #402): begin and complete both require the
# pre-provisioned SETUP_TOKEN, presented as X-Setup-Token.
SETUP_TOKEN = "test-setup-token"
SETUP_HEADERS = {"X-Setup-Token": SETUP_TOKEN}

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def setup_token(monkeypatch: pytest.MonkeyPatch):
    """Give every test a configured setup token to present."""
    monkeypatch.setattr(config, "SETUP_TOKEN", SETUP_TOKEN)


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
    await seed_account(
        session, "existing@dojo.test", user_id=user_id, role="admin", is_active=True
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
    await seed_account(
        session,
        "phantom@dojo.test",
        user_id=str(uuid.uuid4()),
        role="member",
        is_active=True,
        pending_challenge="dGVzdC1jaGFsbGVuZ2U",
        challenge_issued_at=datetime.now(UTC),
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
    await seed_account(
        session,
        "no-cred@dojo.test",
        user_id=str(uuid.uuid4()),
        role="admin",
        is_active=True,
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
    await seed_account(
        session, "founder@dojo.test", user_id=user_id, role="admin", is_active=True
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
            json={"email": "admin@dojo.test", "first_name": "Ai", "surname": "Sato"},
            headers=SETUP_HEADERS,
        )
    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]


@pytest.mark.asyncio
async def test_setup_claim_creates_the_first_admins_member_and_account(
    db_client,
) -> None:
    """#432: there is no sign-in without a kendoka, the first Admin included."""
    from app.members.db_models import Member

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/setup/passkey/begin",
            json={"email": "sensei@dojo.test", "first_name": "Ai", "surname": "Sato"},
            headers=SETUP_HEADERS,
        )
    assert response.status_code == 200

    member = (
        await db_client.execute(
            select(Member).where(Member.email == "sensei@dojo.test")
        )
    ).scalar_one()
    assert (member.first_name, member.surname) == ("Ai", "Sato")
    account = (
        await db_client.execute(select(User).where(User.member_id == member.id))
    ).scalar_one()
    # Admin is granted when the claim completes, not here (#432 review).
    assert account.role == "member"


@pytest.mark.parametrize(
    "body",
    [
        {"email": "sensei@dojo.test"},
        {"email": "sensei@dojo.test", "first_name": "", "surname": "Sato"},
    ],
    ids=["no-names", "blank-first-name"],
)
@pytest.mark.asyncio
async def test_setup_claim_without_names_is_422(db_client, body) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/setup/passkey/begin", json=body, headers=SETUP_HEADERS
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_setup_passkey_begin_returns_404_when_populated(db_client) -> None:
    """POST /setup/passkey/begin returns 404 when instance already has a PasskeyCredential."""
    session = db_client
    user_id = str(uuid.uuid4())
    await seed_account(
        session, "alreadyhere@dojo.test", user_id=user_id, role="admin", is_active=True
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
            json={"email": "newcomer@dojo.test", "first_name": "Ai", "surname": "Sato"},
            headers=SETUP_HEADERS,
        )
    assert response.status_code == 404
    assert response.json().get("detail") == "Setup already completed"


# ── AC5: Successful registration via setup → admin + cookie ──────────────────


@pytest.mark.asyncio
async def test_setup_passkey_complete_creates_admin_and_sets_cookie(db_client) -> None:
    """POST /setup/passkey/complete on a fresh instance registers an admin user
    and sets the access_token cookie (AC5)."""
    session = db_client

    # Seed what /setup/passkey/begin leaves: a member-role Account with a
    # pending challenge. Completing the claim is what makes it admin (#432).
    user_id = str(uuid.uuid4())
    await seed_account(
        session,
        "admin@dojo.test",
        user_id=user_id,
        role="member",
        is_active=True,
        pending_challenge="dGVzdC1jaGFsbGVuZ2U",
        challenge_issued_at=datetime.now(UTC),
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
                headers=SETUP_HEADERS,
            )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "admin@dojo.test"
    assert body["role"] == "admin"
    assert "access_token" in response.cookies
    stored = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one()
    assert stored.role == "admin"


@pytest.mark.asyncio
async def test_setup_passkey_complete_returns_404_when_populated(db_client) -> None:
    """POST /setup/passkey/complete returns 404 when instance already has a
    PasskeyCredential (AC5 guard)."""
    session = db_client

    existing_id = str(uuid.uuid4())
    pending_id = str(uuid.uuid4())
    await seed_account(
        session, "original@dojo.test", user_id=existing_id, role="admin", is_active=True
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
    await seed_account(
        session,
        "newcomer@dojo.test",
        user_id=pending_id,
        role="member",
        is_active=True,
        pending_challenge="dGVzdC1jaGFsbGVuZ2U",
        challenge_issued_at=datetime.now(UTC),
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
                headers=SETUP_HEADERS,
            )

    assert response.status_code == 404
    assert response.json().get("detail") == "Setup already completed"


# ── ADR-0003 / #402: the claim gate ───────────────────────────────────────────

_CREDENTIAL_PAYLOAD = {
    "email": "admin@dojo.test",
    "credential": {
        "id": "c2V0dXAtY3JlZGVudGlhbC1pZA",
        "rawId": "c2V0dXAtY3JlZGVudGlhbC1pZA",
        "response": {"clientDataJSON": "dGVzdA", "attestationObject": "dGVzdA"},
        "type": "public-key",
    },
}


async def _post(path: str, json: dict, headers: dict | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        return await c.post(path, json=json, headers=headers or {})


@pytest.mark.parametrize(
    "path,payload",
    [
        (
            "/setup/passkey/begin",
            {"email": "admin@dojo.test", "first_name": "Ai", "surname": "Sato"},
        ),
        ("/setup/passkey/complete", _CREDENTIAL_PAYLOAD),
    ],
)
@pytest.mark.parametrize(
    "headers",
    # The non-ASCII case is sent as raw bytes: Starlette decodes headers as
    # latin-1, and comparing the resulting str would raise TypeError inside
    # secrets.compare_digest — a 500 where a 401 belongs.
    [
        None,
        {"X-Setup-Token": "wrong-token"},
        {"X-Setup-Token": "wr\xf6ng".encode("latin-1")},
    ],
    ids=["missing", "wrong", "non-ascii"],
)
@pytest.mark.asyncio
async def test_setup_requires_setup_token(
    db_client, path: str, payload: dict, headers: dict | None
) -> None:
    """An unclaimed instance refuses both ceremonies without the right token."""
    response = await _post(path, payload, headers)
    assert response.status_code == 401
    assert response.json().get("detail") == "Invalid setup token"


@pytest.mark.parametrize(
    "path,payload",
    [
        (
            "/setup/passkey/begin",
            {"email": "admin@dojo.test", "first_name": "Ai", "surname": "Sato"},
        ),
        ("/setup/passkey/complete", _CREDENTIAL_PAYLOAD),
    ],
)
@pytest.mark.asyncio
async def test_setup_rejects_blank_configured_token(
    db_client, monkeypatch: pytest.MonkeyPatch, path: str, payload: dict
) -> None:
    """A blank SETUP_TOKEN never matches — not even a blank header.

    validate_startup_config() refuses to boot without one, but anything that
    skips lifespan() must not fall through to "" == "" and open the claim.
    """
    monkeypatch.setattr(config, "SETUP_TOKEN", "")
    response = await _post(path, payload, {"X-Setup-Token": ""})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "path,payload",
    [
        (
            "/setup/passkey/begin",
            {"email": "newcomer@dojo.test", "first_name": "Ai", "surname": "Sato"},
        ),
        ("/setup/passkey/complete", _CREDENTIAL_PAYLOAD),
    ],
)
@pytest.mark.parametrize(
    "headers",
    [None, {"X-Setup-Token": "wrong-token"}, SETUP_HEADERS],
    ids=["missing", "wrong", "right"],
)
@pytest.mark.asyncio
async def test_claimed_instance_404s_whatever_token_is_presented(
    db_client, path: str, payload: dict, headers: dict | None
) -> None:
    """The existing claimed guard still runs first: 404 beats any token."""
    session = db_client
    user_id = str(uuid.uuid4())
    await seed_account(
        session, "claimed@dojo.test", user_id=user_id, role="admin", is_active=True
    )
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_id=b"claimed-cred",
            public_key=b"claimed-pubkey",
            sign_count=0,
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()

    response = await _post(path, payload, headers)
    assert response.status_code == 404
    assert response.json().get("detail") == "Setup already completed"


# ── The claim gate is not bypassable via the ordinary registration route ──────


@pytest.mark.asyncio
async def test_ordinary_register_begin_cannot_bootstrap_an_admin(db_client) -> None:
    """/auth/register/passkey/begin presents no setup token, so on an unclaimed
    instance it must take the decoy path rather than the bootstrap branch —
    which would create a role="admin" user row for any email a stranger sends.
    """
    session = db_client
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/register/passkey/begin", json={"email": "stranger@dojo.test"}
        )

    assert response.status_code == 200  # decoy is indistinguishable by shape
    rows = await session.execute(
        select(User)
        .join(Member, Member.id == User.member_id)
        .where(Member.email == "stranger@dojo.test")
    )
    assert rows.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_ordinary_register_complete_rejected_on_unclaimed_instance(
    db_client,
) -> None:
    """A phantom admin row left by setup's begin must not be completable through
    the ordinary registration route, which carries no setup token."""
    session = db_client
    await seed_account(
        session,
        "admin@dojo.test",
        user_id=str(uuid.uuid4()),
        role="admin",
        is_active=True,
        pending_challenge="dGVzdC1jaGFsbGVuZ2U",
        challenge_issued_at=datetime.now(UTC),
    )
    await session.flush()

    mock_verified = MagicMock()
    mock_verified.credential_id = b"hijacked-credential-id"
    mock_verified.credential_public_key = b"hijacked-public-key"
    mock_verified.sign_count = 0

    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/auth/register/passkey/complete", json=_CREDENTIAL_PAYLOAD
            )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_an_abandoned_claim_leaves_no_admin_to_take_over(db_client) -> None:
    """#432 review: a claim begun under one address and finished under another
    leaves the first attempt's Member and Account behind, with no passkey.
    Once the instance is claimed, the ordinary registration route can reach
    that Account (its Member is on the roster), so it must not be an admin:
    admin is granted when a claim completes, never when one begins."""
    session = db_client
    abandoned = await _post(
        "/setup/passkey/begin",
        {"email": "typo@dojo.tst", "first_name": "Ai", "surname": "Sato"},
        SETUP_HEADERS,
    )
    assert abandoned.status_code == 200

    # The claim then completes under the right address; here, any passkey
    # anywhere ends bootstrap.
    claimant = await seed_account(session, "sensei@dojo.test", role="admin")
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=claimant,
            credential_id=b"claimant-cred",
            public_key=b"claimant-key",
            sign_count=0,
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()

    await _post("/auth/register/passkey/begin", {"email": "typo@dojo.tst"})
    mock_verified = MagicMock(
        credential_id=b"stranger-cred",
        credential_public_key=b"stranger-key",
        sign_count=0,
        aaguid=None,
    )
    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        completed = await _post(
            "/auth/register/passkey/complete",
            {**_CREDENTIAL_PAYLOAD, "email": "typo@dojo.tst"},
        )

    assert completed.status_code == 201, completed.text
    assert completed.json()["role"] == "member"
