"""Tests for the passkey email-enumeration fix (issue #239).

Two auth-boundary weaknesses are being closed in app.auth.passkey_service:

1. login_passkey_begin used to 404 for unknown emails but return a real
   WebAuthn challenge for known ones -- an email-enumeration oracle.
2. register_passkey_begin -> _get_or_create_user used to create a User row
   for ANY email, unauthenticated.

The new design:
- Registration is gated on an admin-created Member row matching the email.
  The zero-User bootstrap is preserved (first-ever registrant becomes admin
  regardless of Member rows).
- A successful register-begin links the matching Member.user_id to the new
  User's id.
- Both begin endpoints return HTTP 200 with a well-formed decoy publicKey
  challenge for unauthorized/unknown emails, freshly random on every call
  just like the real path, and never touch the DB on that path.
- The complete endpoints fail with a generic, indistinguishable error when
  following a decoy begin.

Written against sqlite in-memory, following the fixture conventions in
test_passkey.py.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.db_models import PasskeyCredential, User
from app.db.base import Base
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app
from app.members.db_models import Member

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


async def _seed_user(engine, email: str, role: str = "member") -> str:
    """Seed a fully-registered user: a User row plus a PasskeyCredential.

    The credential is what makes the instance count as "already set up" --
    register_passkey_begin defines bootstrap as zero PasskeyCredential rows,
    not zero User rows, so that a phantom user left behind by an abandoned
    first-run ceremony cannot permanently brick setup.
    """
    user_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            insert(User).values(
                id=user_id,
                email=email,
                role=role,
                is_active=True,
            )
        )
        await conn.execute(
            insert(PasskeyCredential).values(
                id=str(uuid.uuid4()),
                user_id=user_id,
                credential_id=uuid.uuid4().bytes,
                public_key=b"seeded-public-key",
                sign_count=0,
            )
        )
    return user_id


async def _seed_phantom_user(engine, email: str, role: str = "member") -> str:
    """Seed a User with NO credential -- an abandoned registration ceremony."""
    user_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            insert(User).values(
                id=user_id,
                email=email,
                role=role,
                is_active=True,
            )
        )
    return user_id


async def _seed_member(engine, email: str) -> str:
    member_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
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
    return member_id


async def _user_count(engine) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(select(User))
        return len(result.fetchall())


# ── AC1/AC2: registration gated on admin-created Member ─────────────────────


@pytest.mark.anyio
async def test_register_begin_unauthorized_email_creates_no_user(db_client) -> None:
    """Register-begin for an email with no matching Member creates no User row,
    when the instance already has at least one User (bootstrap not in play)."""
    engine = db_client
    await _seed_user(engine, "existing-admin@dojo.test", role="admin")
    before = await _user_count(engine)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "unauthorized@dojo.test"},
        )

    assert response.status_code == 200
    after = await _user_count(engine)
    assert after == before

    async with engine.connect() as conn:
        result = await conn.execute(
            select(User).where(User.email == "unauthorized@dojo.test")
        )
        assert result.fetchone() is None


@pytest.mark.anyio
async def test_register_begin_authorized_email_creates_user(db_client) -> None:
    """Register-begin for an email matching an admin-created Member creates
    the User row and returns a real (non-decoy) challenge."""
    engine = db_client
    await _seed_user(engine, "existing-admin@dojo.test", role="admin")
    member_id = await _seed_member(engine, "authorized@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "authorized@dojo.test"},
        )

    assert response.status_code == 200
    async with engine.connect() as conn:
        result = await conn.execute(
            select(User).where(User.email == "authorized@dojo.test")
        )
        user_row = result.fetchone()
        member_result = await conn.execute(select(Member).where(Member.id == member_id))
        member_row = member_result.fetchone()
    assert user_row is not None
    # A "real" (non-decoy) begin must also perform the Member->User link --
    # today's implementation never sets Member.user_id at all.
    assert member_row is not None
    assert member_row.user_id == user_row.id


@pytest.mark.anyio
async def test_register_begin_links_member_user_id(db_client) -> None:
    """After a successful register-begin, the matching Member's user_id
    equals the newly-created User's id."""
    engine = db_client
    await _seed_user(engine, "existing-admin@dojo.test", role="admin")
    member_id = await _seed_member(engine, "linkme@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "linkme@dojo.test"},
        )
    assert response.status_code == 200

    async with engine.connect() as conn:
        user_result = await conn.execute(
            select(User).where(User.email == "linkme@dojo.test")
        )
        user_row = user_result.fetchone()
        member_result = await conn.execute(select(Member).where(Member.id == member_id))
        member_row = member_result.fetchone()

    assert user_row is not None
    assert member_row is not None
    assert member_row.user_id == user_row.id


@pytest.mark.anyio
async def test_register_begin_bootstrap_zero_users_creates_admin(db_client) -> None:
    """On a fresh instance with zero Users, register-begin succeeds for any
    email (no Member required) and the created User gets role 'admin'. If a
    Member row happens to match, it is still linked."""
    engine = db_client
    assert await _user_count(engine) == 0
    member_id = await _seed_member(engine, "first-ever@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "first-ever@dojo.test"},
        )

    assert response.status_code == 200
    async with engine.connect() as conn:
        result = await conn.execute(
            select(User).where(User.email == "first-ever@dojo.test")
        )
        user_row = result.fetchone()
        member_result = await conn.execute(select(Member).where(Member.id == member_id))
        member_row = member_result.fetchone()
    assert user_row is not None
    assert user_row.role == "admin"
    # Even during bootstrap, a matching Member must be linked -- today's
    # implementation never sets Member.user_id at all.
    assert member_row is not None
    assert member_row.user_id == user_row.id


@pytest.mark.anyio
async def test_abandoned_first_run_ceremony_does_not_brick_setup(db_client) -> None:
    """A phantom User from an abandoned first-run ceremony must not end
    bootstrap.

    Regression test for the security review of issue #239. register-begin
    inserts the User row *before* the interactive WebAuthn ceremony finishes.
    If bootstrap were defined as count(User) == 0, abandoning that ceremony
    once -- closing the tab, an incompatible browser -- would flip bootstrap
    off forever. No Member row exists yet on a fresh instance, so every
    retry, including one with the same email, would get a decoy and the
    instance could never be set up without direct DB surgery.
    """
    engine = db_client
    await _seed_phantom_user(engine, "first-ever@dojo.test", role="admin")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        retry = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "first-ever@dojo.test"},
        )

    assert retry.status_code == 200
    async with engine.connect() as conn:
        result = await conn.execute(
            select(User).where(User.email == "first-ever@dojo.test")
        )
        user_row = result.fetchone()
    # Still reachable as a real registration, not a decoy: the retry must
    # arm a pending challenge on the existing phantom row.
    assert user_row is not None
    assert user_row.pending_challenge is not None


# ── AC5/AC6: decoy challenge shape, no 404 leak ──────────────────────────────


@pytest.mark.anyio
async def test_login_begin_unknown_email_returns_200_not_404(db_client) -> None:
    """login_passkey_begin for an unknown email returns 200 with a
    well-formed publicKey challenge -- not a 404."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
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
    assert body["publicKey"].get("allowCredentials") == []


@pytest.mark.anyio
async def test_login_begin_known_and_unknown_email_shapes_match(db_client) -> None:
    """The response shape for a known email (real challenge) and an unknown
    email (decoy challenge) must be indistinguishable -- same keys."""
    engine = db_client
    await _seed_user(engine, "known@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
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


@pytest.mark.anyio
async def test_register_begin_authorized_and_unauthorized_shapes_match(
    db_client,
) -> None:
    """AC6 at the HTTP layer: the register-begin response for an authorized
    email (real challenge) and an unauthorized one (decoy) must be
    indistinguishable -- same keys, and same encoded widths.

    Converted from a Playwright stub. The browser could only observe that
    both attempts reach the same generic client-side failure, which is a
    weaker claim than this: a real WebAuthn ceremony cannot complete in
    headless Chromium without a virtual authenticator, so the UI test could
    never actually reach the interesting part. The indistinguishability
    claim lives in the HTTP response, so it is asserted here.

    The user id width check is not incidental -- the decoy originally used a
    32-byte sha256 digest while the real path uses a 36-char UUID string,
    which made the encoded user id itself an enumeration tell.
    """
    engine = db_client
    await _seed_user(engine, "existing-admin@dojo.test", role="admin")
    await _seed_member(engine, "authorized@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        authorized = await c.post(
            "/auth/register/passkey/begin", json={"email": "authorized@dojo.test"}
        )
        unauthorized = await c.post(
            "/auth/register/passkey/begin", json={"email": "nobody@dojo.test"}
        )

    assert authorized.status_code == unauthorized.status_code == 200
    auth_key = authorized.json()["publicKey"]
    unauth_key = unauthorized.json()["publicKey"]
    assert set(auth_key.keys()) == set(unauth_key.keys())
    assert len(auth_key["challenge"]) == len(unauth_key["challenge"])
    assert len(auth_key["user"]["id"]) == len(unauth_key["user"]["id"])
    assert set(auth_key["user"].keys()) == set(unauth_key["user"].keys())


@pytest.mark.anyio
async def test_register_begin_unauthorized_email_returns_200_decoy(db_client) -> None:
    """register_passkey_begin for an unauthorized email returns 200 with a
    well-formed decoy challenge, not an error."""
    engine = db_client
    await _seed_user(engine, "existing-admin@dojo.test", role="admin")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "unauthorized2@dojo.test"},
        )

    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]
    assert isinstance(body["publicKey"]["challenge"], str)
    assert len(body["publicKey"]["challenge"]) > 0
    # A well-formed decoy must not be a *real* challenge -- no User row for
    # the unauthorized email may exist afterwards.
    async with engine.connect() as conn:
        result = await conn.execute(
            select(User).where(User.email == "unauthorized2@dojo.test")
        )
        assert result.fetchone() is None


# ── AC7: decoy challenges are random per call, like the real path ────────────
#
# These two tests originally asserted the OPPOSITE (a deterministic,
# HMAC-derived decoy). That requirement was wrong and was itself the
# strongest enumeration oracle in the fix: the real begin endpoints let
# py_webauthn draw a fresh random challenge on every call, so a decoy that
# repeated for a given email let an attacker classify any address with two
# requests and no timing analysis. Decoys must be random per call.


@pytest.mark.anyio
async def test_login_begin_decoy_challenge_differs_per_call(db_client) -> None:
    """Two login-begin calls for the same unknown email return DIFFERENT
    challenges, matching the real path's per-call randomness."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
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


@pytest.mark.anyio
async def test_register_begin_decoy_challenge_differs_per_call(db_client) -> None:
    """Two register-begin calls for the same unauthorized email return
    DIFFERENT decoy challenges."""
    engine = db_client
    await _seed_user(engine, "existing-admin@dojo.test", role="admin")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        first = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "repeat-probe-reg@dojo.test"},
        )
        second = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "repeat-probe-reg@dojo.test"},
        )

    assert first.status_code == second.status_code == 200
    assert (
        first.json()["publicKey"]["challenge"]
        != second.json()["publicKey"]["challenge"]
    )


# ── AC8: decoy paths write nothing to the DB ─────────────────────────────────


@pytest.mark.anyio
async def test_login_begin_decoy_path_writes_no_db_rows(db_client) -> None:
    """login_passkey_begin for an unknown email must not create a User row
    nor mutate any pending_challenge."""
    engine = db_client
    before = await _user_count(engine)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/login/passkey/begin", json={"email": "ghost@dojo.test"}
        )

    assert response.status_code == 200
    after = await _user_count(engine)
    assert after == before


@pytest.mark.anyio
async def test_register_begin_decoy_path_writes_no_db_rows(db_client) -> None:
    """register_passkey_begin for an unauthorized email must not create a
    User row."""
    engine = db_client
    await _seed_user(engine, "existing-admin@dojo.test", role="admin")
    before = await _user_count(engine)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/register/passkey/begin",
            json={"email": "ghost-register@dojo.test"},
        )

    assert response.status_code == 200
    after = await _user_count(engine)
    assert after == before


# ── AC9: complete endpoints fail generically after a decoy begin ────────────


@pytest.mark.anyio
async def test_login_complete_after_decoy_begin_fails_generic(db_client) -> None:
    """login_passkey_complete for an email that never had a real begin (i.e.
    followed a decoy begin) must fail with a generic error -- not the
    user-enumerating 404 'User not found'."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
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


@pytest.mark.anyio
async def test_register_complete_after_decoy_begin_fails_generic(db_client) -> None:
    """register_passkey_complete for an unauthorized email (which only ever
    got a decoy begin) must fail with a generic error -- not the
    user-enumerating 404 'User not found'."""
    engine = db_client
    await _seed_user(engine, "existing-admin@dojo.test", role="admin")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/register/passkey/begin",
            json={"email": "phantom-register@dojo.test"},
        )
        response = await c.post(
            "/auth/register/passkey/complete",
            json={
                "email": "phantom-register@dojo.test",
                "credential": {
                    "id": "ZmFrZQ",
                    "rawId": "ZmFrZQ",
                    "response": {
                        "clientDataJSON": "dGVzdA",
                        "attestationObject": "dGVzdA",
                    },
                    "type": "public-key",
                },
            },
        )

    assert response.status_code != 404
    assert response.json().get("detail") != "User not found"


@pytest.mark.anyio
async def test_login_complete_errors_indistinguishable_unknown_vs_bad_credential(
    db_client,
) -> None:
    """The error returned for 'no such user' and 'wrong credential' must be
    identical in status code and detail -- the whole point of AC9."""
    engine = db_client
    known_user_id = await _seed_user(engine, "known-nocred@dojo.test")
    # Give the known user a pending challenge as if login-begin had run for real.
    async with engine.begin() as conn:
        await conn.execute(
            User.__table__.update()
            .where(User.id == known_user_id)
            .values(
                pending_challenge="dGVzdC1jaGFsbGVuZ2U",
                challenge_issued_at=datetime.now(UTC),
            )
        )

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
        transport=ASGITransport(app=app), base_url="http://test"
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
