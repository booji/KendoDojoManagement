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
from app.auth.db_models import Account, PasskeyCredential
from app.main import app
from app.members.db_models import Member
from tests.account_support import seed_account, seed_member

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
    """GET /setup returns 200 when the accounts table is empty (fresh instance)."""
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
    await seed_account(session, "existing@dojo.test", user_id=user_id, role="admin")
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
    await seed_account(session, "founder@dojo.test", user_id=user_id, role="admin")
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
        await db_client.execute(select(Account).where(Account.member_id == member.id))
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
    await seed_account(session, "alreadyhere@dojo.test", user_id=user_id, role="admin")
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
        await session.execute(select(Account).where(Account.id == user_id))
    ).scalar_one()
    assert stored.role == "admin"


@pytest.mark.asyncio
async def test_setup_passkey_complete_returns_404_when_populated(db_client) -> None:
    """POST /setup/passkey/complete returns 404 when instance already has a
    PasskeyCredential (AC5 guard)."""
    session = db_client

    existing_id = str(uuid.uuid4())
    pending_id = str(uuid.uuid4())
    await seed_account(session, "original@dojo.test", user_id=existing_id, role="admin")
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
    await seed_account(session, "claimed@dojo.test", user_id=user_id, role="admin")
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


# ── A claim cannot take an Account somebody holds ─────────────────────────────


@pytest.mark.asyncio
async def test_a_claim_cannot_take_an_account_that_holds_recovery_codes(
    db_client,
) -> None:
    """Setup reopens once the last passkey on the instance is gone. An Admin
    who deleted their only passkey while holding recovery codes still owns
    their Account, so a claim under their address must not enrol on it."""
    from app.auth.db_models import RecoveryCode

    session = db_client
    user_id = await seed_account(session, "sensei@dojo.test", role="admin")
    await session.execute(
        insert(RecoveryCode).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            code_hash="hash",
            set_id=str(uuid.uuid4()),
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()

    begun = await _post(
        "/setup/passkey/begin",
        {"email": "sensei@dojo.test", "first_name": "Ai", "surname": "Sato"},
        SETUP_HEADERS,
    )
    assert begun.status_code == 200
    mock_verified = MagicMock(
        credential_id=b"claim-cred",
        credential_public_key=b"claim-key",
        sign_count=0,
        aaguid=None,
    )
    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        completed = await _post(
            "/setup/passkey/complete",
            {**_CREDENTIAL_PAYLOAD, "email": "sensei@dojo.test"},
            SETUP_HEADERS,
        )

    assert completed.status_code == 401
    stored = await session.execute(
        select(PasskeyCredential).where(PasskeyCredential.user_id == user_id)
    )
    assert stored.first() is None


async def _members_and_accounts(session, email: str) -> tuple[int, int]:
    members = (
        await session.execute(select(Member.id).where(Member.email == email))
    ).all()
    accounts = (
        await session.execute(
            select(Account.id)
            .join(Member, Member.id == Account.member_id)
            .where(Member.email == email)
        )
    ).all()
    return len(members), len(accounts)


@pytest.mark.asyncio
async def test_completing_a_claim_removes_abandoned_claim_attempts(db_client) -> None:
    """#446: a claim begun under one address and finished under another must
    not leave the first attempt's Member on the roster, or its Account. A
    Member who was on the roster
    before the claim is never removed or altered (an Account a claim attempt
    made for it stays: it cannot be told from one the Member made)."""
    session = db_client
    roster = await seed_member(session, "kendoka@dojo.test", first_name="Ken")
    await session.flush()

    # Abandoned twice -- once under an address nobody has, once under a roster
    # Member's -- then completed under the right one.
    for email in ("typo@dojo.tst", "kendoka@dojo.test", "sensei@dojo.test"):
        begun = await _post(
            "/setup/passkey/begin",
            {"email": email, "first_name": "Ai", "surname": "Sato"},
            SETUP_HEADERS,
        )
        assert begun.status_code == 200
    mock_verified = MagicMock(
        credential_id=b"claim-cred",
        credential_public_key=b"claim-key",
        sign_count=0,
        aaguid=None,
    )
    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        completed = await _post(
            "/setup/passkey/complete",
            {**_CREDENTIAL_PAYLOAD, "email": "sensei@dojo.test"},
            SETUP_HEADERS,
        )
    assert completed.status_code == 201, completed.text

    assert await _members_and_accounts(session, "typo@dojo.tst") == (0, 0)
    assert await _members_and_accounts(session, "sensei@dojo.test") == (1, 1)
    kept = await session.get(Member, roster)
    await session.refresh(kept)
    assert (kept.email, kept.first_name) == ("kendoka@dojo.test", "Ken")
    assert kept.claim_attempted_at is None
    claimant = (
        await session.execute(select(Member).where(Member.email == "sensei@dojo.test"))
    ).scalar_one()
    assert claimant.claim_attempted_at is None


@pytest.mark.asyncio
async def test_claim_cleanup_removes_whatever_an_abandoned_attempt_gathered(
    db_client,
) -> None:
    """An operator can mint a recovery token (cli.py create-recovery-token) or
    try a redemption against an abandoned attempt's address before the claim
    completes; neither may stop the cleanup."""
    from datetime import timedelta

    from app.auth.db_models import AdminRecoveryToken, RecoveryAttempt

    session = db_client
    begun = await _post(
        "/setup/passkey/begin",
        {"email": "typo@dojo.tst", "first_name": "Ai", "surname": "Sato"},
        SETUP_HEADERS,
    )
    assert begun.status_code == 200
    abandoned = (
        await session.execute(
            select(Account.id)
            .join(Member, Member.id == Account.member_id)
            .where(Member.email == "typo@dojo.tst")
        )
    ).scalar_one()
    now = datetime.now(UTC)
    await session.execute(
        insert(AdminRecoveryToken).values(
            id=str(uuid.uuid4()),
            user_id=abandoned,
            token_hash="hash",
            expires_at=now + timedelta(hours=1),
            created_at=now,
        )
    )
    await session.execute(
        insert(RecoveryAttempt).values(
            id=str(uuid.uuid4()),
            user_id=abandoned,
            attempted_at=now,
            ip_address="127.0.0.1",
            success=False,
        )
    )
    await session.flush()

    await _post(
        "/setup/passkey/begin",
        {"email": "sensei@dojo.test", "first_name": "Ai", "surname": "Sato"},
        SETUP_HEADERS,
    )
    mock_verified = MagicMock(
        credential_id=b"claim-cred",
        credential_public_key=b"claim-key",
        sign_count=0,
        aaguid=None,
    )
    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        completed = await _post(
            "/setup/passkey/complete",
            {**_CREDENTIAL_PAYLOAD, "email": "sensei@dojo.test"},
            SETUP_HEADERS,
        )

    assert completed.status_code == 201, completed.text
    assert await _members_and_accounts(session, "typo@dojo.tst") == (0, 0)


@pytest.mark.asyncio
async def test_a_failed_cleanup_does_not_fail_a_completed_claim(
    db_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim has committed by the time abandoned attempts are removed; an
    error there must not turn it into a 500 the claimant cannot retry."""
    from sqlalchemy.exc import OperationalError

    import app.routers.setup as setup_router

    async def broken(*_args) -> None:
        raise OperationalError("DELETE", {}, Exception("boom"))

    monkeypatch.setattr(setup_router, "_discard_abandoned_claims", broken)
    await _post(
        "/setup/passkey/begin",
        {"email": "sensei@dojo.test", "first_name": "Ai", "surname": "Sato"},
        SETUP_HEADERS,
    )
    mock_verified = MagicMock(
        credential_id=b"claim-cred",
        credential_public_key=b"claim-key",
        sign_count=0,
        aaguid=None,
    )
    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        completed = await _post(
            "/setup/passkey/complete",
            {**_CREDENTIAL_PAYLOAD, "email": "sensei@dojo.test"},
            SETUP_HEADERS,
        )

    assert completed.status_code == 201, completed.text
    assert completed.json()["role"] == "admin"
    assert "access_token" in completed.cookies
