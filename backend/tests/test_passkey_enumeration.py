"""Tests for the passkey email-enumeration fix (issue #239).

Two auth-boundary weaknesses are being closed in app.auth.passkey_service:

1. login_passkey_begin used to 404 for unknown emails but return a real
   WebAuthn challenge for known ones -- an email-enumeration oracle.
2. register_passkey_begin -> _get_or_create_user used to create an Account row
   for ANY email, unauthenticated.

The design:
- Login begin returns HTTP 200 with a well-formed decoy publicKey challenge
  for unknown emails, freshly random on every call just like the real path,
  and never touches the DB on that path.
- Login complete fails with a generic, indistinguishable error when
  following a decoy begin.
- The zero-Account bootstrap lives behind the setup token (ADR-0003).

The email-addressed register ceremony this issue gated on a Member row is
gone altogether: Members join by invite only (#472). Its decoy-shape
guarantees now belong to invite redemption (test_invites.py).

Written against the shared PostgreSQL test database via the `db_client`
fixture (conftest.py; savepoint-scoped, rolled back per test), following the
fixture conventions in test_passkey.py.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, insert, select

import app.config as config
from app.auth.db_models import (
    Account,
    AdminRecoveryToken,
    Invite,
    PasskeyCredential,
    RecoveryAttempt,
    RecoveryCode,
)
from app.main import app
from app.members.db_models import Member
from tests.account_support import seed_account

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


# The bootstrap branch lives behind the setup token now (ADR-0003, #402).
_SETUP_HEADERS = {"X-Setup-Token": "test-setup-token"}


@pytest.fixture(autouse=True)
def _setup_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SETUP_TOKEN", _SETUP_HEADERS["X-Setup-Token"])


async def _seed_user(session, email: str, role: str = "member") -> str:
    """Seed a fully-registered user: an Account row plus a PasskeyCredential."""
    user_id = str(uuid.uuid4())
    await seed_account(session, email, user_id=user_id, role=role)
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_id=uuid.uuid4().bytes,
            public_key=b"seeded-public-key",
            sign_count=0,
        )
    )
    await session.flush()
    return user_id


async def _seed_phantom_user(session, email: str) -> str:
    """Seed an Account with NO credential -- an abandoned registration ceremony."""
    user_id = str(uuid.uuid4())
    await seed_account(session, email, user_id=user_id)
    await session.flush()
    return user_id


async def _seed_credentials(session, user_id: str, count: int) -> None:
    """Add `count` extra PasskeyCredential rows for an already-seeded user.

    Used to vary N independently of _seed_user/_seed_phantom_user, which fix
    the credential count at 1 and 0 respectively.
    """
    for _ in range(count):
        await session.execute(
            insert(PasskeyCredential).values(
                id=str(uuid.uuid4()),
                user_id=user_id,
                credential_id=uuid.uuid4().bytes,
                public_key=b"seeded-public-key",
                sign_count=0,
            )
        )
    await session.flush()


async def _seed_member(session, email: str) -> str:
    member_id = str(uuid.uuid4())
    await session.execute(
        insert(Member).values(
            id=member_id,
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
    return member_id


async def _reset_to_fresh_instance(session) -> None:
    """Clear every auth row so the test sees a genuinely fresh instance.

    The bootstrap tests below assert on the zero-Account / zero-credential state
    a brand-new deployment starts in. On the shared PostgreSQL test database
    that state has to be established rather than assumed: rows committed
    outside a savepoint by other tests (e.g. the e2e seed) are still visible
    here. Everything deleted here is inside `db_session`'s savepoint, so it
    is rolled back on teardown and no other test observes the wipe.

    Ordered children-first: the auth rows carry a FK to accounts.id, and accounts
    one to members.id (#432).
    """
    for table in (
        PasskeyCredential.__table__,
        RecoveryCode.__table__,
        RecoveryAttempt.__table__,
        AdminRecoveryToken.__table__,
        Invite.__table__,
        Account.__table__,
        Member.__table__,
    ):
        await session.execute(delete(table))
    await session.flush()


async def _user_count(session) -> int:
    result = await session.execute(select(Account))
    return len(result.fetchall())


# ── First-admin claim (bootstrap) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_begin_bootstrap_zero_users_creates_admin(db_client) -> None:
    """On a fresh instance with zero Accounts, the token-gated setup route succeeds
    for any email (no Member required) and creates the claimant's Account,
    which becomes admin when the claim completes. If a Member row happens to
    match, that Member is the one the Account belongs to.

    The bootstrap branch is reachable only from /setup/passkey/begin, which
    requires the pre-provisioned SETUP_TOKEN (ADR-0003): the ordinary
    registration route below it would otherwise hand admin to any stranger who
    reached an unclaimed instance.
    """
    session = db_client
    await _reset_to_fresh_instance(session)
    assert await _user_count(session) == 0
    member_id = await _seed_member(session, "first-ever@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/setup/passkey/begin",
            json={
                "email": "first-ever@dojo.test",
                "first_name": "Ai",
                "surname": "Sato",
            },
            headers=_SETUP_HEADERS,
        )

    assert response.status_code == 200
    result = await session.execute(
        select(Account)
        .join(Member, Member.id == Account.member_id)
        .where(Member.email == "first-ever@dojo.test")
    )
    user_row = result.scalar_one_or_none()
    member_result = await session.execute(select(Member).where(Member.id == member_id))
    member_row = member_result.scalar_one_or_none()
    assert user_row is not None
    # A member until the claim completes: admin is granted by setup's
    # complete, never by a begin (#432 review).
    assert user_row.role == "member"
    # Even during bootstrap, a matching Member is the one the Account
    # belongs to, rather than a second Member for the same address.
    assert member_row is not None
    assert user_row.member_id == member_row.id


@pytest.mark.asyncio
async def test_abandoned_first_run_ceremony_does_not_brick_setup(db_client) -> None:
    """A phantom Account from an abandoned first-run ceremony must not end
    bootstrap.

    Regression test for the security review of issue #239. register-begin
    inserts the Account row *before* the interactive WebAuthn ceremony finishes.
    If bootstrap were defined as count(Account) == 0, abandoning that ceremony
    once -- closing the tab, an incompatible browser -- would flip bootstrap
    off forever. No Member row exists yet on a fresh instance, so every
    retry, including one with the same email, would get a decoy and the
    instance could never be set up without direct DB surgery.
    """
    session = db_client
    await _reset_to_fresh_instance(session)
    # A member: begin never grants admin, only a completed claim does (#432),
    # and an Admin Account claims the instance (#589).
    await _seed_phantom_user(session, "first-ever@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        retry = await c.post(
            "/setup/passkey/begin",
            json={
                "email": "first-ever@dojo.test",
                "first_name": "Ai",
                "surname": "Sato",
            },
            headers=_SETUP_HEADERS,
        )

    assert retry.status_code == 200
    result = await session.execute(
        select(Account)
        .join(Member, Member.id == Account.member_id)
        .where(Member.email == "first-ever@dojo.test")
    )
    user_row = result.scalar_one_or_none()
    # Still reachable as a real registration, not a decoy: the retry must
    # arm a pending challenge on the existing phantom row.
    assert user_row is not None
    assert user_row.pending_challenge is not None


# ── AC5/AC6: decoy challenge shape, no 404 leak ──────────────────────────────


@pytest.mark.asyncio
async def test_login_begin_unknown_email_returns_200_not_404(db_client) -> None:
    """login_passkey_begin for an unknown email returns 200 with a
    well-formed publicKey challenge -- not a 404."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/login/passkey/begin",
            json={"email": "nobody@dojo.test"},
        )

    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]
    assert isinstance(body["publicKey"]["challenge"], str)
    assert len(body["publicKey"]["challenge"]) > 0
    # issue #267: allowCredentials is removed entirely, not merely emptied --
    # an empty list on the decoy path next to a populated one on the real
    # path was itself the enumeration oracle, so the field is dropped rather
    # than masked.
    assert "allowCredentials" not in body["publicKey"]


@pytest.mark.asyncio
async def test_login_begin_known_and_unknown_email_shapes_match(db_client) -> None:
    """The response shape for a known email (real challenge) and an unknown
    email (decoy challenge) must be indistinguishable -- same keys."""
    session = db_client
    await _seed_user(session, "known@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        known_response = await c.post(
            "/auth/login/passkey/begin", json={"email": "known@dojo.test"}
        )
        unknown_response = await c.post(
            "/auth/login/passkey/begin", json={"email": "nobody@dojo.test"}
        )

    assert known_response.status_code == unknown_response.status_code == 200
    known = known_response.json()["publicKey"]
    unknown = unknown_response.json()["publicKey"]
    assert set(known.keys()) == set(unknown.keys())
    # Length matters as much as key names: a decoy whose challenge encodes to
    # a different width is just as much a tell as a different status code.
    assert len(known["challenge"]) == len(unknown["challenge"])


# ── AC7: decoy challenges are random per call, like the real path ────────────
#
# These two tests originally asserted the OPPOSITE (a deterministic,
# HMAC-derived decoy). That requirement was wrong and was itself the
# strongest enumeration oracle in the fix: the real begin endpoints let
# py_webauthn draw a fresh random challenge on every call, so a decoy that
# repeated for a given email let an attacker classify any address with two
# requests and no timing analysis. Decoys must be random per call.


@pytest.mark.asyncio
async def test_login_begin_decoy_challenge_differs_per_call(db_client) -> None:
    """Two login-begin calls for the same unknown email return DIFFERENT
    challenges, matching the real path's per-call randomness."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        first = await c.post(
            "/auth/login/passkey/begin", json={"email": "repeat-probe@dojo.test"}
        )
        second = await c.post(
            "/auth/login/passkey/begin", json={"email": "repeat-probe@dojo.test"}
        )

    assert first.status_code == second.status_code == 200
    assert (
        first.json()["publicKey"]["challenge"]
        != second.json()["publicKey"]["challenge"]
    )


# ── AC8: decoy paths write nothing to the DB ─────────────────────────────────


@pytest.mark.asyncio
async def test_login_begin_decoy_path_writes_no_db_rows(db_client) -> None:
    """login_passkey_begin for an unknown email must not create an Account row
    nor mutate any pending_challenge."""
    session = db_client
    before = await _user_count(session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/login/passkey/begin", json={"email": "ghost@dojo.test"}
        )

    assert response.status_code == 200
    after = await _user_count(session)
    assert after == before


# ── AC9: complete endpoints fail generically after a decoy begin ────────────


@pytest.mark.asyncio
async def test_login_complete_after_decoy_begin_fails_generic(db_client) -> None:
    """login_passkey_complete for an email that never had a real begin (i.e.
    followed a decoy begin) must fail with a generic error -- not the
    user-enumerating 404 'User not found'."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.post("/auth/login/passkey/begin", json={"email": "phantom@dojo.test"})
        response = await c.post(
            "/auth/login/passkey/complete",
            json={
                "email": "phantom@dojo.test",
                "credential": {
                    "id": "ZmFrZQ",
                    "rawId": "ZmFrZQ",
                    "response": {
                        "clientDataJSON": "dGVzdA",
                        "authenticatorData": "dGVzdA",
                        "signature": "dGVzdA",
                    },
                    "type": "public-key",
                },
            },
        )

    assert response.status_code != 404
    assert response.json().get("detail") != "User not found"


@pytest.mark.asyncio
async def test_login_complete_errors_indistinguishable_unknown_vs_bad_credential(
    db_client,
) -> None:
    """The error returned for 'no such user' and 'wrong credential' must be
    identical in status code and detail -- the whole point of AC9."""
    session = db_client
    known_user_id = await _seed_user(session, "known-nocred@dojo.test")
    # Give the known user a pending challenge as if login-begin had run for real.
    await session.execute(
        Account.__table__.update()
        .where(Account.id == known_user_id)
        .values(
            pending_challenge="dGVzdC1jaGFsbGVuZ2U",
            challenge_issued_at=datetime.now(UTC),
        )
    )
    await session.flush()

    fake_credential = {
        "id": "ZmFrZQ",
        "rawId": "ZmFrZQ",
        "response": {
            "clientDataJSON": "dGVzdA",
            "authenticatorData": "dGVzdA",
            "signature": "dGVzdA",
        },
        "type": "public-key",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        unknown_response = await c.post(
            "/auth/login/passkey/complete",
            json={"email": "unknown-nouser@dojo.test", "credential": fake_credential},
        )
        known_bad_cred_response = await c.post(
            "/auth/login/passkey/complete",
            json={"email": "known-nocred@dojo.test", "credential": fake_credential},
        )

    assert unknown_response.status_code == known_bad_cred_response.status_code
    assert unknown_response.json().get("detail") == known_bad_cred_response.json().get(
        "detail"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_id", ["A", "é"])
async def test_login_complete_malformed_credential_id_same_for_known_and_unknown(
    db_client, credential_id
) -> None:
    """A credential id that is not base64url used to 500 for a known email
    and 401 for an unknown one: a one-request enumeration oracle (#587). Both
    must get the generic 401."""
    await _seed_user(db_client, "known-malformed@dojo.test")
    credential = {
        "id": credential_id,
        "rawId": credential_id,
        "response": {},
        "type": "public-key",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test/api",
    ) as c:
        responses = [
            await c.post(
                "/auth/login/passkey/complete",
                json={"email": email, "credential": credential},
            )
            for email in ("known-malformed@dojo.test", "unknown-malformed@dojo.test")
        ]

    assert [r.status_code for r in responses] == [401, 401]
    assert responses[0].json() == responses[1].json()


# ── issue #267: allowCredentials removed as an enumeration channel ─────────
#
# #239/#255 masked login_passkey_begin's decoy shape and timing, but left
# allowCredentials itself in place: it always grows to one descriptor per
# registered passkey on the real path while the decoy path always returns an
# empty list, so response *size* enumerates registered emails (and how many
# passkeys they have) in a single request -- no statistics needed, unlike the
# timing side channel. The chosen fix removes the field entirely and moves
# login onto discoverable credentials, which also means registration must
# start requesting a resident key so a credential capable of a
# allowCredentials-free login actually gets created.


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_count", [0, 1, 3])
async def test_login_begin_known_email_byte_length_matches_decoy(
    db_client, credential_count
) -> None:
    """AC1: login-begin's response body for a known email with N registered
    passkeys is byte-length-identical to the decoy response for an unknown
    email, for N = 0, 1 and 3.

    Today allowCredentials grows with N on the real path while the decoy
    path's list is always empty, so this must fail for N=1 and N=3 (and would
    only accidentally pass for N=0) until allowCredentials is removed.
    """
    session = db_client
    known_email = f"known-{credential_count}@dojo.test"
    user_id = await _seed_phantom_user(session, known_email)
    await _seed_credentials(session, user_id, credential_count)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        known = await c.post("/auth/login/passkey/begin", json={"email": known_email})
        decoy = await c.post(
            "/auth/login/passkey/begin",
            json={"email": f"unknown-{credential_count}@dojo.test"},
        )

    assert known.status_code == decoy.status_code == 200
    assert len(known.content) == len(decoy.content)


@pytest.mark.asyncio
async def test_login_begin_response_has_no_allow_credentials_key(db_client) -> None:
    """AC2: the login-begin response contains no allowCredentials key at all,
    neither on the real path (known email, multiple passkeys) nor the decoy
    path (unknown email)."""
    session = db_client
    user_id = await _seed_phantom_user(session, "haskeys@dojo.test")
    await _seed_credentials(session, user_id, 2)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        known = await c.post(
            "/auth/login/passkey/begin", json={"email": "haskeys@dojo.test"}
        )
        decoy = await c.post(
            "/auth/login/passkey/begin", json={"email": "nokeys@dojo.test"}
        )

    assert known.status_code == decoy.status_code == 200
    assert "allowCredentials" not in known.json()["publicKey"]
    assert "allowCredentials" not in decoy.json()["publicKey"]


@pytest.mark.asyncio
async def test_begin_endpoints_still_answer_unknown_email_and_stay_constant_time(
    db_client,
) -> None:
    """AC5: removing allowCredentials must not regress the #239/#255
    guarantees -- login begin still accepts an email, still returns 200 for an
    unknown one, and remains listed in the constant-time middleware's
    protected path set. (The email-addressed register begin is gone, #472.)"""
    from app.config import API_PREFIX
    from app.core.middleware import _CONSTANT_TIME_PATHS

    assert f"{API_PREFIX}/auth/login/passkey/begin" in _CONSTANT_TIME_PATHS

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        login_resp = await c.post(
            "/auth/login/passkey/begin", json={"email": "still-answers@dojo.test"}
        )

    assert login_resp.status_code == 200
    # The specific #267 regression check: the old guarantee was shaped around
    # an empty allowCredentials list, a concept this issue removes outright.
    assert "allowCredentials" not in login_resp.json()["publicKey"]


@pytest.mark.asyncio
async def test_login_completes_end_to_end_without_allow_credentials(
    db_client,
) -> None:
    """AC6: passkey login still completes end-to-end for a credential
    registered under the new (discoverable-credential) registration options,
    with login-begin returning no allowCredentials -- proving
    login_passkey_complete resolves the user from (email, credential_id)
    alone rather than depending on a channel this issue removes.

    Runs a full setup claim -> login round trip against a fresh instance,
    mocking only the two webauthn verification calls the
    same way test_passkey.py does, since no real authenticator is available
    here.
    """
    session = db_client
    await _reset_to_fresh_instance(session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        register_begin = await c.post(
            "/setup/passkey/begin",
            json={"email": "e2e-flow@dojo.test", "first_name": "Ai", "surname": "Sato"},
            headers=_SETUP_HEADERS,
        )
        assert register_begin.status_code == 200
        assert (
            register_begin.json()["publicKey"]["authenticatorSelection"]["residentKey"]
            == "required"
        )

        credential_id_bytes = b"e2e-flow-credential-id"
        credential_id_b64 = "ZTJlLWZsb3ctY3JlZGVudGlhbC1pZA"

        mock_verified_registration = MagicMock()
        mock_verified_registration.credential_id = credential_id_bytes
        mock_verified_registration.credential_public_key = b"e2e-flow-public-key"
        mock_verified_registration.sign_count = 0
        mock_verified_registration.aaguid = None

        with patch(
            "webauthn.verify_registration_response",
            return_value=mock_verified_registration,
        ):
            register_complete = await c.post(
                "/setup/passkey/complete",
                headers=_SETUP_HEADERS,
                json={
                    "email": "e2e-flow@dojo.test",
                    "credential": {
                        "id": credential_id_b64,
                        "rawId": credential_id_b64,
                        "response": {
                            "clientDataJSON": "dGVzdA",
                            "attestationObject": "dGVzdA",
                        },
                        "type": "public-key",
                    },
                },
            )
        assert register_complete.status_code == 201

        login_begin = await c.post(
            "/auth/login/passkey/begin", json={"email": "e2e-flow@dojo.test"}
        )
        assert login_begin.status_code == 200
        assert "allowCredentials" not in login_begin.json()["publicKey"]

        mock_verified_login = MagicMock()
        mock_verified_login.credential_id = credential_id_bytes
        mock_verified_login.new_sign_count = 1

        with patch(
            "webauthn.verify_authentication_response",
            return_value=mock_verified_login,
        ):
            login_complete = await c.post(
                "/auth/login/passkey/complete",
                json={
                    "email": "e2e-flow@dojo.test",
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

    assert login_complete.status_code == 200
    assert "access_token" in login_complete.cookies


@pytest.mark.asyncio
async def test_sign_in_ignores_the_case_of_the_email(db_client) -> None:
    """#592: an address claimed as `Kenji@…` signs in as `kenji@…`."""
    await _reset_to_fresh_instance(db_client)
    credential_id_b64 = "Y2FzZS1jcmVkZW50aWFsLWlk"  # b"case-credential-id"

    def credential(response: dict) -> dict:
        return {
            "id": credential_id_b64,
            "rawId": credential_id_b64,
            "response": response,
            "type": "public-key",
        }

    registration = MagicMock(
        credential_id=b"case-credential-id",
        credential_public_key=b"case-public-key",
        sign_count=0,
        aaguid=None,
    )
    login = MagicMock(credential_id=b"case-credential-id", new_sign_count=1)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.post(
            "/setup/passkey/begin",
            json={"email": "Kenji@Dojo.test", "first_name": "Ai", "surname": "Sato"},
            headers=_SETUP_HEADERS,
        )
        with patch("webauthn.verify_registration_response", return_value=registration):
            claimed = await c.post(
                "/setup/passkey/complete",
                headers=_SETUP_HEADERS,
                json={
                    "email": "Kenji@Dojo.test",
                    "credential": credential(
                        {"clientDataJSON": "dGVzdA", "attestationObject": "dGVzdA"}
                    ),
                },
            )
        assert claimed.status_code == 201

        await c.post("/auth/login/passkey/begin", json={"email": "kenji@dojo.test"})
        with patch("webauthn.verify_authentication_response", return_value=login):
            signed_in = await c.post(
                "/auth/login/passkey/complete",
                json={
                    "email": "kenji@dojo.test",
                    "credential": credential(
                        {
                            "clientDataJSON": "dGVzdA",
                            "authenticatorData": "dGVzdA",
                            "signature": "dGVzdA",
                        }
                    ),
                },
            )

    assert signed_in.status_code == 200


# ── Account verification enforcement (issue #267 follow-up) ──────────────────────
#
# Issue #267 made registration request `userVerification: "required"` as part
# of moving login onto discoverable credentials. Requesting UV in the options
# is not the same as enforcing it: py_webauthn's verify_* helpers default
# `require_user_verification=False` and only check the authenticator-data `uv`
# flag when it is True. Without these, the server advertises a guarantee it
# never checks -- a caller driving the API directly (or a patched client) can
# complete a ceremony with a credential that performed no user verification,
# so a stolen unlocked security key is enough to register or log in.


@pytest.mark.asyncio
async def test_login_begin_requests_user_verification_both_paths(db_client) -> None:
    """UV must be requested at login on the real AND decoy path.

    Both matter: enforcing UV at verification while only requesting the
    py_webauthn default ("preferred") would let a conforming authenticator
    skip UV and then be rejected, breaking login. And a decoy that requests
    a different level than the real path is a #239-style shape tell.
    """
    session = db_client
    await _seed_user(session, "uv-known@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        known = await c.post(
            "/auth/login/passkey/begin", json={"email": "uv-known@dojo.test"}
        )
        unknown = await c.post(
            "/auth/login/passkey/begin", json={"email": "uv-nobody@dojo.test"}
        )

    assert known.json()["publicKey"]["userVerification"] == "required"
    assert unknown.json()["publicKey"]["userVerification"] == "required"
    assert len(known.content) == len(unknown.content)


@pytest.mark.asyncio
async def test_ceremony_verification_enforces_user_verification(db_client) -> None:
    """Both complete endpoints must ask py_webauthn to CHECK the uv flag.

    Asserted by spying on the verification calls: py_webauthn only inspects
    authenticator-data's `uv` bit when `require_user_verification=True`, so
    the kwarg at this boundary is the whole enforcement. Driven through a
    real register -> login round trip (same mocking approach as the AC6 test
    above) rather than by reading source, so it stays true if the calls move.
    """
    session = db_client
    await _reset_to_fresh_instance(session)

    credential_id_bytes = b"uv-flow-credential-id"
    credential_id_b64 = "dXYtZmxvdy1jcmVkZW50aWFsLWlk"

    mock_registration = MagicMock()
    mock_registration.credential_id = credential_id_bytes
    mock_registration.credential_public_key = b"uv-flow-public-key"
    mock_registration.sign_count = 0
    mock_registration.aaguid = None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.post(
            "/setup/passkey/begin",
            json={"email": "uv-flow@dojo.test", "first_name": "Ai", "surname": "Sato"},
            headers=_SETUP_HEADERS,
        )

        with patch(
            "webauthn.verify_registration_response", return_value=mock_registration
        ) as reg_spy:
            reg_complete = await c.post(
                "/setup/passkey/complete",
                headers=_SETUP_HEADERS,
                json={
                    "email": "uv-flow@dojo.test",
                    "credential": {
                        "id": credential_id_b64,
                        "rawId": credential_id_b64,
                        "response": {
                            "clientDataJSON": "dGVzdA",
                            "attestationObject": "dGVzdA",
                        },
                        "type": "public-key",
                    },
                },
            )
        assert reg_complete.status_code == 201
        assert reg_spy.call_args.kwargs.get("require_user_verification") is True, (
            "the setup claim does not enforce user verification; the "
            "userVerification='required' advertised at begin is unchecked"
        )

        await c.post("/auth/login/passkey/begin", json={"email": "uv-flow@dojo.test"})

        mock_login = MagicMock()
        mock_login.credential_id = credential_id_bytes
        mock_login.new_sign_count = 1

        with patch(
            "webauthn.verify_authentication_response", return_value=mock_login
        ) as auth_spy:
            login_complete = await c.post(
                "/auth/login/passkey/complete",
                json={
                    "email": "uv-flow@dojo.test",
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
        assert login_complete.status_code == 200
        assert auth_spy.call_args.kwargs.get("require_user_verification") is True, (
            "login_passkey_complete does not enforce user verification"
        )
