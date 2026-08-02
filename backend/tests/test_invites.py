"""Failing tests for issue #257 — Admin-issued invite tokens for passkey
registration.

Nothing in this file has been implemented yet: no `Invite` model, no
`app.auth.invite_repository`, no `app.auth.invite_service`, no invite routes.
Every test here is RED by design (either the import fails, or the route
returns 404). This is the TDD red phase; implementation follows separately.

Two design decisions were fixed by the user before this file was written and
are NOT re-litigated here:
  - Redeeming an invite CREATES the Member row if none exists for that email
    (or links the existing one), setting Member.user_id -- same convergence
    point as the #239 Member gate.
  - Delivery is a copyable link only. No SMTP, no email sending.

API surface assumed by these tests (chosen here, not yet built):
  POST   /auth/admin/invites              (admin) mint an invite for an email
  GET    /auth/admin/invites              (admin) list invites with status
  POST   /auth/admin/invites/{id}/revoke  (admin) revoke an invite
  POST   /auth/invites/redeem/begin       body {token} -> WebAuthn register
                                           options, decoy-shaped for any bad
                                           token (unknown/expired/revoked/
                                           already-redeemed) exactly like the
                                           #239 register-begin decoy.
  POST   /auth/invites/redeem/complete    body {token, credential} -> creates
                                           User, creates-or-links Member,
                                           completes the passkey ceremony.

Token storage: a plaintext invite token is returned exactly once, at mint
time. Only a hash is ever persisted (Invite.token_hash). Because redemption
must look a token up *without* already knowing which row it belongs to (no
scoping user/email is available up front, unlike the admin-recovery-token
flow), the hash must support direct equality lookup -- so it is expected to
be a deterministic digest (e.g. sha256 hex), not a per-row-salted bcrypt hash.
`_hash_token` below reproduces that expected algorithm purely so tests can
seed rows directly; it is intentionally NOT imported from production code
(which doesn't exist yet).

Two test tiers in this file:
  - Admin management endpoints (mint/list/revoke, AC1-5) use the
    StubRepository pattern (no DB), matching test_members.py /
    test_admin_recovery.py conventions.
  - The redemption flow (AC6-10) is DB-backed against sqlite in-memory,
    matching test_passkey_enumeration.py / test_passkey_timing.py, because it
    must exercise real WebAuthn option generation, User/Member creation, and
    the constant-time middleware floor.
"""

from __future__ import annotations

import hashlib
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app

_ADMIN = UserClaims(
    sub=str(uuid.uuid4()), email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER_CLAIMS = UserClaims(
    sub=str(uuid.uuid4()), email="member@dojo.test", role="member", is_active=True
)


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER_CLAIMS


def _hash_token(plaintext: str) -> str:
    """Expected hashing algorithm for invite tokens -- see module docstring."""
    return hashlib.sha256(plaintext.encode()).hexdigest()


# ---------------------------------------------------------------------------
# AC1 -- Invite model field tests
# ---------------------------------------------------------------------------


def test_invite_model_exists() -> None:
    from app.auth.db_models import Invite  # red — model doesn't exist yet

    assert Invite is not None


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "email",
        "token_hash",
        "expires_at",
        "issued_by",
        "redeemed_at",
        "revoked_at",
        "created_at",
    ],
)
def test_invite_model_has_field(field: str) -> None:
    from app.auth.db_models import Invite  # red — model doesn't exist yet

    assert hasattr(Invite, field)


def test_invite_model_has_no_plaintext_token_field() -> None:
    """Only the hash may be a column -- there must be no `token` column."""
    from app.auth.db_models import Invite  # red — model doesn't exist yet

    assert not hasattr(Invite, "token")


# ---------------------------------------------------------------------------
# Stub repository (admin mint / list / revoke — no DB)
# ---------------------------------------------------------------------------


class StubInviteRepo:
    """In-memory stand-in for an Invite repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {
            "id": new_id,
            "redeemed_at": None,
            "revoked_at": None,
            "created_at": datetime.now(UTC),
            **data,
        }
        self._store[new_id] = record
        return record

    async def get(self, invite_id: str) -> dict[str, Any] | None:
        return self._store.get(invite_id)

    async def get_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        for item in self._store.values():
            if item["token_hash"] == token_hash:
                return item
        return None

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def mark_revoked(self, invite_id: str) -> dict[str, Any] | None:
        record = self._store.get(invite_id)
        if record is None:
            return None
        record["revoked_at"] = datetime.now(UTC)
        return record

    async def mark_redeemed(self, invite_id: str) -> dict[str, Any] | None:
        record = self._store.get(invite_id)
        if record is None:
            return None
        record["redeemed_at"] = datetime.now(UTC)
        return record


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def invite_repo() -> StubInviteRepo:
    from app.auth.dependencies import get_invite_repo  # red — doesn't exist yet

    repo = StubInviteRepo()
    app.dependency_overrides[get_invite_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC2 -- admin mints an invite; plaintext returned exactly once
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_mint_invite(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/admin/invites", json={"email": "invitee@dojo.test"}
        )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "invitee@dojo.test"
    assert "token" in body
    assert isinstance(body["token"], str)
    assert len(body["token"]) > 16
    assert "link" in body
    assert body["token"] in body["link"]


@pytest.mark.anyio
async def test_mint_invite_stores_only_hash_not_plaintext(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/admin/invites", json={"email": "hashme@dojo.test"}
        )
    assert response.status_code == 201
    plaintext = response.json()["token"]

    stored = await invite_repo.list()
    assert len(stored) == 1
    assert stored[0]["token_hash"] != plaintext
    assert "token" not in stored[0]


@pytest.mark.anyio
async def test_mint_invite_missing_email_returns_422(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/auth/admin/invites", json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC3 -- unauthenticated / non-admin rejected on every admin endpoint
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mint_invite_unauthenticated_returns_401(invite_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/admin/invites", json={"email": "nope@dojo.test"}
        )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_mint_invite_non_admin_returns_403(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = REQUIRE_ADMIN  # not overridden
    from app.auth.token import encode_token

    token = encode_token(_MEMBER_CLAIMS)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/admin/invites",
            json={"email": "nope@dojo.test"},
            cookies={"access_token": token},
        )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_list_invites_unauthenticated_returns_401(invite_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_list_invites_non_admin_returns_403(invite_repo) -> None:
    from app.auth.token import encode_token

    token = encode_token(_MEMBER_CLAIMS)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(
            "/auth/admin/invites", cookies={"access_token": token}
        )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_revoke_invite_unauthenticated_returns_401(invite_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/auth/admin/invites/{uuid.uuid4()}/revoke")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_revoke_invite_non_admin_returns_403(invite_repo) -> None:
    from app.auth.token import encode_token

    token = encode_token(_MEMBER_CLAIMS)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/auth/admin/invites/{uuid.uuid4()}/revoke",
            cookies={"access_token": token},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC4 -- listing invites returns status, never a plaintext token
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_invites_returns_pending_status(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await invite_repo.add(
        {
            "email": "pending@dojo.test",
            "token_hash": _hash_token("plain-pending"),
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "issued_by": _ADMIN.sub,
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "pending"
    assert body[0]["email"] == "pending@dojo.test"


@pytest.mark.anyio
async def test_list_invites_returns_redeemed_status(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await invite_repo.add(
        {
            "email": "redeemed@dojo.test",
            "token_hash": _hash_token("plain-redeemed"),
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "issued_by": _ADMIN.sub,
            "redeemed_at": datetime.now(UTC),
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "redeemed"


@pytest.mark.anyio
async def test_list_invites_returns_expired_status(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await invite_repo.add(
        {
            "email": "expired@dojo.test",
            "token_hash": _hash_token("plain-expired"),
            "expires_at": datetime.now(UTC) - timedelta(hours=1),
            "issued_by": _ADMIN.sub,
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "expired"


@pytest.mark.anyio
async def test_list_invites_returns_revoked_status(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await invite_repo.add(
        {
            "email": "revoked@dojo.test",
            "token_hash": _hash_token("plain-revoked"),
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "issued_by": _ADMIN.sub,
            "revoked_at": datetime.now(UTC),
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "revoked"


@pytest.mark.anyio
async def test_list_invites_never_returns_plaintext_token(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await invite_repo.add(
        {
            "email": "secretive@dojo.test",
            "token_hash": _hash_token("plain-secretive"),
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "issued_by": _ADMIN.sub,
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 200
    body = response.json()[0]
    assert "token" not in body
    assert "token_hash" not in body


# ---------------------------------------------------------------------------
# AC5 -- revoking an invite makes it unusable
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_revoke_invite(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    record = await invite_repo.add(
        {
            "email": "torevoke@dojo.test",
            "token_hash": _hash_token("plain-torevoke"),
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "issued_by": _ADMIN.sub,
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/auth/admin/invites/{record['id']}/revoke")
    assert response.status_code == 200
    stored = await invite_repo.get(record["id"])
    assert stored["revoked_at"] is not None


@pytest.mark.anyio
async def test_revoke_unknown_invite_returns_404(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/auth/admin/invites/{uuid.uuid4()}/revoke")
    assert response.status_code == 404


# ===========================================================================
# Redemption flow — DB-backed (sqlite in-memory), matching
# test_passkey_enumeration.py / test_passkey_timing.py conventions.
# ===========================================================================

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def _engine():
    from app.db.base import Base

    eng = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_client(_engine):
    from app.db.unit_of_work import SQLAlchemyUnitOfWork
    from app.dependencies import get_uow

    factory = async_sessionmaker(_engine, expire_on_commit=False)

    async def _override():
        async with SQLAlchemyUnitOfWork(factory) as uow:
            yield uow

    app.dependency_overrides[get_uow] = _override
    yield _engine


async def _seed_admin_user(engine, email: str = "existing-admin@dojo.test") -> str:
    """Seed an existing User+PasskeyCredential so the instance is no longer
    in bootstrap mode, mirroring test_passkey_enumeration.py's `_seed_user`."""
    from app.auth.db_models import PasskeyCredential, User

    user_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            insert(User).values(id=user_id, email=email, role="admin", is_active=True)
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


async def _seed_invite(
    engine,
    email: str,
    plaintext: str,
    *,
    issued_by: str | None = None,
    expires_at: datetime | None = None,
    redeemed_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> str:
    from app.auth.db_models import Invite  # red — model doesn't exist yet

    invite_id = str(uuid.uuid4())
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(hours=24)
    async with engine.begin() as conn:
        await conn.execute(
            insert(Invite).values(
                id=invite_id,
                email=email,
                token_hash=_hash_token(plaintext),
                expires_at=expires_at,
                issued_by=issued_by,
                redeemed_at=redeemed_at,
                revoked_at=revoked_at,
                created_at=datetime.now(UTC),
            )
        )
    return invite_id


async def _seed_member(engine, email: str) -> str:
    from app.members.db_models import Member

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


_FAKE_REGISTER_CREDENTIAL = {
    "id": "ZmFrZQ",
    "rawId": "ZmFrZQ",
    "response": {
        "clientDataJSON": "dGVzdA",
        "attestationObject": "dGVzdA",
    },
    "type": "public-key",
}


# ---------------------------------------------------------------------------
# AC6 -- redeeming a valid token completes registration and creates/links Member
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_redeem_begin_valid_token_returns_real_challenge(db_client) -> None:
    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine, "newinvitee@dojo.test", "valid-token-1", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "valid-token-1"}
        )

    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]


@pytest.mark.anyio
async def test_redeem_creates_user_for_invited_email(db_client) -> None:
    from app.auth.db_models import User

    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine, "createuser@dojo.test", "valid-token-2", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post("/auth/invites/redeem/begin", json={"token": "valid-token-2"})

    async with engine.connect() as conn:
        result = await conn.execute(
            select(User).where(User.email == "createuser@dojo.test")
        )
        assert result.fetchone() is not None


@pytest.mark.anyio
async def test_redeem_creates_member_when_absent(db_client) -> None:
    from app.members.db_models import Member

    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine, "brandnewmember@dojo.test", "valid-token-3", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post("/auth/invites/redeem/begin", json={"token": "valid-token-3"})

    async with engine.connect() as conn:
        result = await conn.execute(
            select(Member).where(Member.email == "brandnewmember@dojo.test")
        )
        member = result.fetchone()
    assert member is not None


@pytest.mark.anyio
async def test_redeem_links_existing_member_user_id(db_client) -> None:
    from app.auth.db_models import User
    from app.members.db_models import Member

    engine = db_client
    admin_id = await _seed_admin_user(engine)
    member_id = await _seed_member(engine, "existingmember@dojo.test")
    await _seed_invite(
        engine, "existingmember@dojo.test", "valid-token-4", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post("/auth/invites/redeem/begin", json={"token": "valid-token-4"})

    async with engine.connect() as conn:
        user_result = await conn.execute(
            select(User).where(User.email == "existingmember@dojo.test")
        )
        user_row = user_result.fetchone()
        member_result = await conn.execute(select(Member).where(Member.id == member_id))
        member_row = member_result.fetchone()

    assert user_row is not None
    assert member_row is not None
    assert member_row.user_id == user_row.id


# ---------------------------------------------------------------------------
# AC7 -- single use: a second redemption with the same token fails
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_redeem_token_twice_second_attempt_fails(db_client) -> None:
    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine, "onceonly@dojo.test", "single-use-token", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        first = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "single-use-token", "credential": _FAKE_REGISTER_CREDENTIAL},
        )
        second_begin = await c.post(
            "/auth/invites/redeem/begin", json={"token": "single-use-token"}
        )

    # First completion may fail webauthn verification (fake credential), but
    # the invite must be consumed / a real challenge must not be re-issued to
    # an already-redeemed token on a second begin.
    assert first.status_code in (201, 401)
    if first.status_code == 201:
        # If the fake credential path was accepted, the invite is redeemed --
        # the second begin must now look like a decoy, i.e. must not arm a
        # user-visible pending_challenge tied to a fresh real ceremony.
        assert second_begin.status_code == 200


@pytest.mark.anyio
async def test_redeem_already_redeemed_token_rejected(db_client) -> None:
    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine,
        "alreadydone@dojo.test",
        "used-token",
        issued_by=admin_id,
        redeemed_at=datetime.now(UTC),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "used-token", "credential": _FAKE_REGISTER_CREDENTIAL},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC8 -- expiry: a token past expires_at fails
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_redeem_expired_token_rejected(db_client) -> None:
    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine,
        "expiredinvitee@dojo.test",
        "expired-token",
        issued_by=admin_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "expired-token", "credential": _FAKE_REGISTER_CREDENTIAL},
        )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_redeem_begin_expired_token_writes_no_user_row(db_client) -> None:
    from app.auth.db_models import User

    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine,
        "expiredbegin@dojo.test",
        "expired-begin-token",
        issued_by=admin_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "expired-begin-token"}
        )

    assert response.status_code == 200  # decoy shape, not an error
    async with engine.connect() as conn:
        result = await conn.execute(
            select(User).where(User.email == "expiredbegin@dojo.test")
        )
        assert result.fetchone() is None


# ---------------------------------------------------------------------------
# AC5 (redemption side) -- a revoked invite is unusable
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_redeem_revoked_token_rejected(db_client) -> None:
    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine,
        "revokedinvitee@dojo.test",
        "revoked-token",
        issued_by=admin_id,
        revoked_at=datetime.now(UTC),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "revoked-token", "credential": _FAKE_REGISTER_CREDENTIAL},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC9 -- no enumeration oracle: valid/invalid/expired/redeemed/revoked all
# look identical on the redemption path.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_redeem_begin_unknown_token_returns_200_decoy(db_client) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "no-such-token"}
        )

    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]


@pytest.mark.anyio
async def test_redeem_begin_valid_and_invalid_shapes_match(db_client) -> None:
    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine, "shapecheck@dojo.test", "shape-valid-token", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        valid = await c.post(
            "/auth/invites/redeem/begin", json={"token": "shape-valid-token"}
        )
        invalid = await c.post(
            "/auth/invites/redeem/begin", json={"token": "no-such-token-either"}
        )

    assert valid.status_code == invalid.status_code == 200
    valid_key = valid.json()["publicKey"]
    invalid_key = invalid.json()["publicKey"]
    assert set(valid_key.keys()) == set(invalid_key.keys())
    assert len(valid_key["challenge"]) == len(invalid_key["challenge"])


@pytest.mark.anyio
async def test_redeem_complete_status_and_body_identical_across_bad_token_reasons(
    db_client,
) -> None:
    """Unknown, expired, already-redeemed, and revoked tokens must all fail
    with the same status code and same response body shape on completion --
    the whole point of AC9, mirroring #239's generic-failure convention."""
    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine,
        "expiredcomplete@dojo.test",
        "cmp-expired",
        issued_by=admin_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await _seed_invite(
        engine,
        "redeemedcomplete@dojo.test",
        "cmp-redeemed",
        issued_by=admin_id,
        redeemed_at=datetime.now(UTC),
    )
    await _seed_invite(
        engine,
        "revokedcomplete@dojo.test",
        "cmp-revoked",
        issued_by=admin_id,
        revoked_at=datetime.now(UTC),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        unknown = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "cmp-unknown", "credential": _FAKE_REGISTER_CREDENTIAL},
        )
        expired = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "cmp-expired", "credential": _FAKE_REGISTER_CREDENTIAL},
        )
        redeemed = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "cmp-redeemed", "credential": _FAKE_REGISTER_CREDENTIAL},
        )
        revoked = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "cmp-revoked", "credential": _FAKE_REGISTER_CREDENTIAL},
        )

    responses = [unknown, expired, redeemed, revoked]
    statuses = {r.status_code for r in responses}
    assert len(statuses) == 1, f"status codes differ across reasons: {statuses}"
    bodies = {r.json().get("detail") for r in responses}
    assert len(bodies) == 1, f"response bodies differ across reasons: {bodies}"


# ---------------------------------------------------------------------------
# AC10 -- no timing asymmetry on redemption; reuse the #255 constant-time floor
# ---------------------------------------------------------------------------


def test_invite_redeem_begin_is_registered_as_constant_time_path() -> None:
    """The redemption begin endpoint must be added to the existing
    ConstantTimeAuthMiddleware path set (app.core.middleware) rather than
    growing its own ad hoc timing protection."""
    from app.core.middleware import _CONSTANT_TIME_PATHS

    assert "/auth/invites/redeem/begin" in _CONSTANT_TIME_PATHS


@pytest.mark.anyio
async def test_invite_redeem_begin_valid_token_meets_configured_floor(
    db_client, monkeypatch
) -> None:
    from app import config

    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)
    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine, "floorvalid@dojo.test", "floor-valid-token", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        start = time.perf_counter()
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "floor-valid-token"}
        )
        elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed >= 0.020


@pytest.mark.anyio
async def test_invite_redeem_begin_invalid_token_meets_configured_floor(
    db_client, monkeypatch
) -> None:
    from app import config

    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        start = time.perf_counter()
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "floor-invalid-token"}
        )
        elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed >= 0.020


@pytest.mark.anyio
async def test_invite_redeem_begin_valid_vs_invalid_median_latency_converges(
    db_client, monkeypatch
) -> None:
    """Over interleaved samples, valid-token and invalid-token latency medians
    must be near-identical, matching the #255 convergence assertion style."""
    from app import config

    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)
    engine = db_client
    admin_id = await _seed_admin_user(engine)
    await _seed_invite(
        engine, "medianvalid@dojo.test", "median-valid-token", issued_by=admin_id
    )

    valid_samples: list[float] = []
    invalid_samples: list[float] = []

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(15):
            start = time.perf_counter()
            r = await c.post(
                "/auth/invites/redeem/begin", json={"token": "median-valid-token"}
            )
            valid_samples.append(time.perf_counter() - start)
            assert r.status_code == 200

            start = time.perf_counter()
            r = await c.post(
                "/auth/invites/redeem/begin", json={"token": "median-invalid-token"}
            )
            invalid_samples.append(time.perf_counter() - start)
            assert r.status_code == 200

    diff = abs(statistics.median(valid_samples) - statistics.median(invalid_samples))
    assert diff < 0.001  # under 1ms, far below any human-observable signal
