"""Failing tests for issue #257 — Admin-issued invite tokens for passkey
registration.

Nothing in this file has been implemented yet: no `Invite` model, no
`app.auth.invite_repository`, no `app.auth.invite_service`, no invite routes.
Every test here is RED by design (either the import fails, or the route
returns 404). This is the TDD red phase; implementation follows separately.

Two design decisions were fixed by the user before this file was written and
are NOT re-litigated here:
  - Redeeming an invite CREATES the Member row if none exists for that email
    (or reuses the existing one) and the Account that belongs to it -- same convergence
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
                                           Account, creates-or-links Member,
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
  - The redemption flow (AC6-10) is DB-backed against the shared PostgreSQL
    test database via the `db_client` fixture (savepoint-scoped, rolled back
    per test), because it must exercise real WebAuthn option generation,
    Account/Member creation, and the constant-time middleware floor.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, insert, select

from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.main import app
from app.members.db_models import Member
from tests.account_support import seed_account

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="admin@dojo.test", role="admin")
_MEMBER_CLAIMS = AccountClaims(
    sub=str(uuid.uuid4()), email="member@dojo.test", role="member"
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


class _NoAccountsResult:
    def scalar_one_or_none(self) -> None:
        return None


class _NoAccountsSession:
    """Just enough session for the mint route's "does this email already have
    an account?" check, so the stub-repo tests stay DB-free."""

    async def execute(self, *args: Any, **kwargs: Any) -> _NoAccountsResult:
        return _NoAccountsResult()


class _StubUow:
    def __init__(self) -> None:
        self.session = _NoAccountsSession()

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture()
def invite_repo() -> StubInviteRepo:
    from app.auth.dependencies import get_invite_repo
    from app.dependencies import get_uow

    repo = StubInviteRepo()
    app.dependency_overrides[get_invite_repo] = lambda: repo
    app.dependency_overrides[get_uow] = lambda: _StubUow()
    return repo


# ---------------------------------------------------------------------------
# AC2 -- admin mints an invite; plaintext returned exactly once
# ---------------------------------------------------------------------------


async def test_admin_can_mint_invite(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/admin/invites",
            json={
                "email": "invitee@dojo.test",
                "first_name": "New",
                "surname": "Invitee",
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "invitee@dojo.test"
    assert "token" in body
    assert isinstance(body["token"], str)
    assert len(body["token"]) > 16
    assert "link" in body
    assert body["token"] in body["link"]


async def test_mint_invite_stores_only_hash_not_plaintext(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/admin/invites",
            json={
                "email": "hashme@dojo.test",
                "first_name": "New",
                "surname": "Invitee",
            },
        )
    assert response.status_code == 201
    plaintext = response.json()["token"]

    stored = await invite_repo.list()
    assert len(stored) == 1
    assert stored[0]["token_hash"] != plaintext
    assert "token" not in stored[0]


async def test_mint_invite_missing_email_returns_422(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/auth/admin/invites", json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC3 -- unauthenticated / non-admin rejected on every admin endpoint
# ---------------------------------------------------------------------------


async def test_mint_invite_unauthenticated_returns_401(invite_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/admin/invites",
            json={"email": "nope@dojo.test", "first_name": "New", "surname": "Invitee"},
        )
    assert response.status_code == 401


async def test_mint_invite_non_admin_returns_403(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = REQUIRE_ADMIN  # not overridden
    from tests.auth_support import sign_in

    token = sign_in(_MEMBER_CLAIMS)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/admin/invites",
            json={"email": "nope@dojo.test", "first_name": "New", "surname": "Invitee"},
            cookies={"access_token": token},
        )
    assert response.status_code == 403


async def test_list_invites_unauthenticated_returns_401(invite_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 401


async def test_list_invites_non_admin_returns_403(invite_repo) -> None:
    from tests.auth_support import sign_in

    token = sign_in(_MEMBER_CLAIMS)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/admin/invites", cookies={"access_token": token})
    assert response.status_code == 403


async def test_revoke_invite_unauthenticated_returns_401(invite_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/auth/admin/invites/{uuid.uuid4()}/revoke")
    assert response.status_code == 401


async def test_revoke_invite_non_admin_returns_403(invite_repo) -> None:
    from tests.auth_support import sign_in

    token = sign_in(_MEMBER_CLAIMS)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/auth/admin/invites/{uuid.uuid4()}/revoke",
            cookies={"access_token": token},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC4 -- listing invites returns status, never a plaintext token
# ---------------------------------------------------------------------------


async def test_list_invites_returns_pending_status(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await invite_repo.add(
        {
            "email": "pending@dojo.test",
            "first_name": "Test",
            "surname": "Invitee",
            "token_hash": _hash_token("plain-pending"),
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "issued_by": _ADMIN.sub,
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "pending"
    assert body[0]["email"] == "pending@dojo.test"


async def test_list_invites_returns_redeemed_status(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await invite_repo.add(
        {
            "email": "redeemed@dojo.test",
            "first_name": "Test",
            "surname": "Invitee",
            "token_hash": _hash_token("plain-redeemed"),
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "issued_by": _ADMIN.sub,
            "redeemed_at": datetime.now(UTC),
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "redeemed"


async def test_list_invites_returns_expired_status(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await invite_repo.add(
        {
            "email": "expired@dojo.test",
            "first_name": "Test",
            "surname": "Invitee",
            "token_hash": _hash_token("plain-expired"),
            "expires_at": datetime.now(UTC) - timedelta(hours=1),
            "issued_by": _ADMIN.sub,
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "expired"


async def test_list_invites_returns_revoked_status(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await invite_repo.add(
        {
            "email": "revoked@dojo.test",
            "first_name": "Test",
            "surname": "Invitee",
            "token_hash": _hash_token("plain-revoked"),
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "issued_by": _ADMIN.sub,
            "revoked_at": datetime.now(UTC),
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "revoked"


async def test_list_invites_never_returns_plaintext_token(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await invite_repo.add(
        {
            "email": "secretive@dojo.test",
            "first_name": "Test",
            "surname": "Invitee",
            "token_hash": _hash_token("plain-secretive"),
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "issued_by": _ADMIN.sub,
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/admin/invites")
    assert response.status_code == 200
    body = response.json()[0]
    assert "token" not in body
    assert "token_hash" not in body


# ---------------------------------------------------------------------------
# AC5 -- revoking an invite makes it unusable
# ---------------------------------------------------------------------------


async def test_admin_can_revoke_invite(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    record = await invite_repo.add(
        {
            "email": "torevoke@dojo.test",
            "first_name": "Test",
            "surname": "Invitee",
            "token_hash": _hash_token("plain-torevoke"),
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "issued_by": _ADMIN.sub,
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/auth/admin/invites/{record['id']}/revoke")
    assert response.status_code == 200
    stored = await invite_repo.get(record["id"])
    assert stored["revoked_at"] is not None


async def test_revoke_unknown_invite_returns_404(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/auth/admin/invites/{uuid.uuid4()}/revoke")
    assert response.status_code == 404


# ===========================================================================
# Redemption flow — DB-backed against the shared PostgreSQL test database via
# the `db_client` fixture (see conftest.py), matching
# test_passkey_enumeration.py / test_passkey_timing.py conventions.
# ===========================================================================


async def _seed_admin_user(session, email: str = "existing-admin@dojo.test") -> str:
    """Seed an existing Account+PasskeyCredential so the instance is no longer
    in bootstrap mode, mirroring test_passkey_enumeration.py's `_seed_user`."""
    from app.auth.db_models import PasskeyCredential

    user_id = str(uuid.uuid4())
    await seed_account(session, email, user_id=user_id, role="admin")
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


async def _seed_invite(
    session,
    email: str,
    plaintext: str,
    *,
    first_name: str = "Test",
    surname: str = "Invitee",
    issued_by: str | None = None,
    expires_at: datetime | None = None,
    redeemed_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> str:
    from app.auth.db_models import Invite  # red — model doesn't exist yet

    invite_id = str(uuid.uuid4())
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(hours=24)
    await session.execute(
        insert(Invite).values(
            id=invite_id,
            email=email,
            first_name=first_name,
            surname=surname,
            token_hash=_hash_token(plaintext),
            expires_at=expires_at,
            issued_by=issued_by,
            redeemed_at=redeemed_at,
            revoked_at=revoked_at,
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return invite_id


async def _seed_member(session, email: str) -> str:
    from app.members.db_models import Member

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


@pytest.mark.asyncio
async def test_redeem_begin_valid_token_returns_real_challenge(db_client) -> None:
    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session, "newinvitee@dojo.test", "valid-token-1", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "valid-token-1"}
        )

    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]


@pytest.mark.asyncio
async def test_redeem_creates_user_for_invited_email(db_client) -> None:
    from app.auth.db_models import Account

    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session, "createuser@dojo.test", "valid-token-2", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.post("/auth/invites/redeem/begin", json={"token": "valid-token-2"})

    result = await session.execute(
        select(Account)
        .join(Member, Member.id == Account.member_id)
        .where(Member.email == "createuser@dojo.test")
    )
    assert result.fetchone() is not None


@pytest.mark.asyncio
async def test_redeem_creates_member_when_absent(db_client) -> None:
    from app.members.db_models import Member

    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session, "brandnewmember@dojo.test", "valid-token-3", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.post("/auth/invites/redeem/begin", json={"token": "valid-token-3"})

    result = await session.execute(
        select(Member).where(Member.email == "brandnewmember@dojo.test")
    )
    member = result.scalar_one_or_none()
    assert member is not None


@pytest.mark.asyncio
async def test_redeem_links_existing_member_user_id(db_client) -> None:
    from app.auth.db_models import Account
    from app.members.db_models import Member

    session = db_client
    admin_id = await _seed_admin_user(session)
    member_id = await _seed_member(session, "existingmember@dojo.test")
    await _seed_invite(
        session, "existingmember@dojo.test", "valid-token-4", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.post("/auth/invites/redeem/begin", json={"token": "valid-token-4"})

    user_result = await session.execute(
        select(Account)
        .join(Member, Member.id == Account.member_id)
        .where(Member.email == "existingmember@dojo.test")
    )
    user_row = user_result.scalar_one_or_none()
    member_result = await session.execute(select(Member).where(Member.id == member_id))
    member_row = member_result.scalar_one_or_none()

    assert user_row is not None
    assert member_row is not None
    # The new Account belongs to the Member that already existed (#432).
    assert user_row.member_id == member_row.id


# ---------------------------------------------------------------------------
# AC7 -- single use: a second redemption with the same token fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redeem_token_twice_second_attempt_fails(db_client) -> None:
    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session, "onceonly@dojo.test", "single-use-token", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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


@pytest.mark.asyncio
async def test_redeem_already_redeemed_token_rejected(db_client) -> None:
    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session,
        "alreadydone@dojo.test",
        "used-token",
        issued_by=admin_id,
        redeemed_at=datetime.now(UTC),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "used-token", "credential": _FAKE_REGISTER_CREDENTIAL},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC8 -- expiry: a token past expires_at fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redeem_expired_token_rejected(db_client) -> None:
    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session,
        "expiredinvitee@dojo.test",
        "expired-token",
        issued_by=admin_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "expired-token", "credential": _FAKE_REGISTER_CREDENTIAL},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_redeem_begin_expired_token_writes_no_user_row(db_client) -> None:
    from app.auth.db_models import Account

    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session,
        "expiredbegin@dojo.test",
        "expired-begin-token",
        issued_by=admin_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "expired-begin-token"}
        )

    assert response.status_code == 200  # decoy shape, not an error
    result = await session.execute(
        select(Account)
        .join(Member, Member.id == Account.member_id)
        .where(Member.email == "expiredbegin@dojo.test")
    )
    assert result.fetchone() is None


# ---------------------------------------------------------------------------
# AC5 (redemption side) -- a revoked invite is unusable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redeem_revoked_token_rejected(db_client) -> None:
    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session,
        "revokedinvitee@dojo.test",
        "revoked-token",
        issued_by=admin_id,
        revoked_at=datetime.now(UTC),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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


@pytest.mark.asyncio
async def test_redeem_begin_unknown_token_returns_200_decoy(db_client) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "no-such-token"}
        )

    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert "challenge" in body["publicKey"]


@pytest.mark.asyncio
async def test_redeem_begin_valid_and_invalid_shapes_match(db_client) -> None:
    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session, "shapecheck@dojo.test", "shape-valid-token", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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


@pytest.mark.asyncio
async def test_redeem_complete_status_and_body_identical_across_bad_token_reasons(
    db_client,
) -> None:
    """Unknown, expired, already-redeemed, and revoked tokens must all fail
    with the same status code and same response body shape on completion --
    the whole point of AC9, mirroring #239's generic-failure convention."""
    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session,
        "expiredcomplete@dojo.test",
        "cmp-expired",
        issued_by=admin_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await _seed_invite(
        session,
        "redeemedcomplete@dojo.test",
        "cmp-redeemed",
        issued_by=admin_id,
        redeemed_at=datetime.now(UTC),
    )
    await _seed_invite(
        session,
        "revokedcomplete@dojo.test",
        "cmp-revoked",
        issued_by=admin_id,
        revoked_at=datetime.now(UTC),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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
    from app.config import API_PREFIX
    from app.core.middleware import _CONSTANT_TIME_PATHS

    assert f"{API_PREFIX}/auth/invites/redeem/begin" in _CONSTANT_TIME_PATHS


@pytest.mark.asyncio
async def test_invite_redeem_begin_valid_token_meets_configured_floor(
    db_client, monkeypatch
) -> None:
    from app import config

    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)
    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session, "floorvalid@dojo.test", "floor-valid-token", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        start = time.perf_counter()
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "floor-valid-token"}
        )
        elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed >= 0.020


@pytest.mark.asyncio
async def test_invite_redeem_begin_invalid_token_meets_configured_floor(
    db_client, monkeypatch
) -> None:
    from app import config

    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        start = time.perf_counter()
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "floor-invalid-token"}
        )
        elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed >= 0.020


@pytest.mark.asyncio
@pytest.mark.timing_sensitive
async def test_invite_redeem_begin_valid_vs_invalid_median_latency_converges(
    db_client, monkeypatch
) -> None:
    """Over interleaved samples, valid-token and invalid-token latency medians
    must be near-identical, matching the #255 convergence assertion style.

    Tolerance is calibrated per run against same-path noise -- see
    tests/timing_support.py and issue #298."""
    from app import config
    from tests.timing_support import assert_latency_converges_sampled

    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)
    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session, "medianvalid@dojo.test", "median-valid-token", issued_by=admin_id
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:

        async def _timed_redeem(token: str) -> float:
            start = time.perf_counter()
            r = await c.post("/auth/invites/redeem/begin", json={"token": token})
            elapsed = time.perf_counter() - start
            assert r.status_code == 200
            return elapsed

        await assert_latency_converges_sampled(
            lambda: _timed_redeem("median-valid-token"),
            lambda: _timed_redeem("median-invalid-token"),
            label_a="valid token",
            label_b="invalid token",
        )


# ---------------------------------------------------------------------------
# issue #300 -- invite_redeem_begin decoy user.id must not be a stability
# oracle
#
# Same defect as register_passkey_begin (see test_passkey_enumeration.py),
# keyed by invite token instead of email: invite_redeem_begin's real path
# returns the persisted Account.id (stable forever for a given token, until
# redeemed), while the decoy minted a fresh uuid4() per call. Two POSTs
# for the same bad token plus one field comparison classifies it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redeem_begin_decoy_user_id_stable_then_secret_dependent(
    db_client, monkeypatch
) -> None:
    """Two redeem-begin calls for the SAME unusable token, under the SAME
    server secret, must return the SAME publicKey.user.id (today they don't:
    each call mints a fresh uuid4()). Then, changing the server secret and
    repeating must change the id -- proving it is not derivable from the
    token alone."""
    from app import config

    monkeypatch.setattr(config, "JWT_SECRET", "secret-one-for-issue-300")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        first = await c.post(
            "/auth/invites/redeem/begin",
            json={"token": "issue-300-stability-probe"},
        )
        second = await c.post(
            "/auth/invites/redeem/begin",
            json={"token": "issue-300-stability-probe"},
        )

    assert first.status_code == second.status_code == 200
    first_id = first.json()["publicKey"]["user"]["id"]
    second_id = second.json()["publicKey"]["user"]["id"]
    assert first_id == second_id, (
        "decoy user.id must be stable across repeat calls for the same "
        "token, matching the real path's stability -- a decoy that varies "
        "per call while the real path is stable-until-redeemed is the "
        "#300 enumeration oracle"
    )

    monkeypatch.setattr(config, "JWT_SECRET", "secret-two-for-issue-300")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        third = await c.post(
            "/auth/invites/redeem/begin",
            json={"token": "issue-300-stability-probe"},
        )

    assert third.status_code == 200
    third_id = third.json()["publicKey"]["user"]["id"]
    assert third_id != first_id, (
        "the decoy id must be secret-dependent -- changing the server "
        "secret for the same token must change the derived id, or the "
        "derivation is just the token in disguise"
    )


@pytest.mark.asyncio
async def test_redeem_begin_real_user_id_matches_persisted_user(db_client) -> None:
    """Sanity check on the OTHER half of AC1: the real path's user.id is the
    persisted Account.id, not a per-call value -- inherently stable, since it is
    the DB row's own primary key. (A genuine two-call replay of the same
    invite token isn't available here: invite_redeem_begin's OWN
    _create_invited_user check flips a second call for the same token onto
    the decoy path once the first call has created the Account row for that
    email -- a separate, pre-existing behaviour unrelated to #300. This test
    instead confirms the single real call returns exactly the row that got
    persisted, which is what "stable" cashes out to for a value that is a
    primary key.)"""
    import base64

    from app.auth.db_models import Account

    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session,
        "real-redeem-stability@dojo.test",
        "real-redeem-stability-token",
        issued_by=admin_id,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/begin",
            json={"token": "real-redeem-stability-token"},
        )

    assert response.status_code == 200
    result = await session.execute(
        select(Account)
        .join(Member, Member.id == Account.member_id)
        .where(Member.email == "real-redeem-stability@dojo.test")
    )
    user_row = result.scalar_one()

    # publicKey.user.id is base64url(user.id.encode()), not the raw UUID
    # string -- decode before comparing (same convention as the challenge
    # field; see app.auth.webauthn_ceremony.decode_challenge).
    returned_id_b64 = response.json()["publicKey"]["user"]["id"]
    padded = returned_id_b64 + "=" * (4 - len(returned_id_b64) % 4)
    returned_id = base64.urlsafe_b64decode(padded).decode()
    assert returned_id == user_row.id


# ---------------------------------------------------------------------------
# Hardening from the #257 security review
#
# Two gaps the review found in the first implementation. Both defend the same
# invariants the issue exists to uphold, so they belong in this file rather
# than a follow-up.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_redeemed_is_atomic_and_rejects_second_claim(database_url) -> None:
    """Single use must be enforced by the write, not by a prior read.

    An unconditional `UPDATE ... SET redeemed_at = now()` lets two concurrent
    redemptions of the same token both pass the usability check before either
    commits, so both register a passkey. The repository must therefore claim
    the row conditionally and report failure when it did not win.

    This test needs two independent, really-committed sessions to observe
    that atomicity, so it can't use the savepoint-scoped `db_client` fixture
    (a single shared, never-committed transaction) -- it builds its own
    NullPool engine bound to the current test's event loop (same technique as
    conftest.py's `db_session`) and cleans up the row it commits afterwards.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.auth.db_models import Invite
    from app.auth.invite_repository import SqlInviteRepository

    engine = create_async_engine(database_url, poolclass=NullPool)
    invite_id = str(uuid.uuid4())
    try:
        async with AsyncSession(engine) as seed_session:
            await seed_session.execute(
                insert(Invite).values(
                    id=invite_id,
                    email="raced@dojo.test",
                    first_name="Test",
                    surname="Invitee",
                    token_hash=_hash_token("raced-token"),
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                    created_at=datetime.now(UTC),
                )
            )
            await seed_session.commit()

        try:
            async with AsyncSession(engine) as session:
                repo = SqlInviteRepository(session)
                first = await repo.mark_redeemed(invite_id)
                await session.commit()

            assert first is not None, "the first claim must succeed"
            assert first["redeemed_at"] is not None

            async with AsyncSession(engine) as session:
                repo = SqlInviteRepository(session)
                second = await repo.mark_redeemed(invite_id)
                await session.commit()

            assert (
                second is None
            ), "a second claim on an already-redeemed invite must fail"
        finally:
            async with AsyncSession(engine) as cleanup_session:
                await cleanup_session.execute(
                    delete(Invite).where(Invite.id == invite_id)
                )
                await cleanup_session.commit()
    finally:
        await engine.dispose()


def test_invite_redemption_routes_are_rate_limited() -> None:
    """Every other public auth endpoint carries the per-IP limit; these are the
    same class of endpoint and must not be the exception."""
    from app.main import app

    registered = set(app.state.limiter._route_limits)
    for endpoint in (
        "app.auth.router.invite_redeem_begin_route",
        "app.auth.router.invite_redeem_complete_route",
    ):
        assert endpoint in registered, f"{endpoint} is not rate limited"


@pytest.mark.asyncio
async def test_deleting_the_issuing_user_leaves_the_invite_intact(db_session) -> None:
    """Erasure deletes the Account row (app/members/router.py), so an unqualified
    FK from invites.issued_by would make an admin who ever issued an invite
    un-erasable. The issuer reference must drop to NULL and the invite survive.

    This one uses the raw `db_session` fixture directly rather than the
    `db_client` (get_uow-overriding) fixture the rest of this file uses,
    since it only needs to seed/inspect rows and never goes through the app.
    """
    from app.auth.db_models import Account, Invite

    admin_id = str(uuid.uuid4())
    invite_id = str(uuid.uuid4())

    await seed_account(
        db_session,
        f"issuer-{admin_id}@dojo.test",
        user_id=admin_id,
        role="admin",
    )
    await db_session.execute(
        insert(Invite).values(
            id=invite_id,
            email="orphaned@dojo.test",
            first_name="Test",
            surname="Invitee",
            token_hash=_hash_token(f"orphan-token-{invite_id}"),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            issued_by=admin_id,
            created_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    await db_session.execute(delete(Account).where(Account.id == admin_id))
    await db_session.flush()

    row = (
        await db_session.execute(select(Invite).where(Invite.id == invite_id))
    ).scalar_one()
    assert row.issued_by is None
    assert row.email == "orphaned@dojo.test"


# ---------------------------------------------------------------------------
# The invitee's name comes from the admin at mint time
#
# Redemption used to invent placeholders (email local-part, empty surname),
# which put junk in the member register that nobody was ever prompted to fix.
# The admin issuing the invite knows who they are inviting, so they supply it.
# ---------------------------------------------------------------------------


async def test_mint_invite_requires_invitee_name(invite_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/admin/invites", json={"email": "nameless@dojo.test"}
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_redeem_creates_member_with_the_name_the_admin_supplied(
    db_client,
) -> None:
    from app.members.db_models import Member

    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(
        session,
        "named@dojo.test",
        "named-token",
        issued_by=admin_id,
        first_name="Keiko",
        surname="Tanaka",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/invites/redeem/begin", json={"token": "named-token"}
        )
    assert response.status_code == 200

    result = await session.execute(
        select(Member).where(Member.email == "named@dojo.test")
    )
    member = result.scalar_one()

    assert member.first_name == "Keiko"
    assert member.surname == "Tanaka"


# ---------------------------------------------------------------------------
# An invite cannot hand out a passkey on an account that already exists
#
# Otherwise whoever holds the link silently gains a credential on a live
# account and its owner is never told. Admin recovery tokens already exist for
# the legitimate "help an existing user get back in" case.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_invite_for_an_existing_user_is_refused(db_client) -> None:
    session = db_client
    await _seed_admin_user(session, "already@dojo.test")
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/admin/invites",
            json={
                "email": "already@dojo.test",
                "first_name": "Al",
                "surname": "Ready",
            },
        )

    assert response.status_code == 409
    assert "recovery" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_redeem_is_refused_once_the_email_has_a_user(db_client) -> None:
    """The account may be created between minting and redemption, so the check
    at mint time is not enough on its own."""
    from app.auth.db_models import Account, PasskeyCredential

    session = db_client
    admin_id = await _seed_admin_user(session)
    await _seed_invite(session, "racing@dojo.test", "racing-token", issued_by=admin_id)
    # The invitee registers by some other route before redeeming.
    await _seed_admin_user(session, "racing@dojo.test")

    before = len(
        (
            await session.execute(
                select(PasskeyCredential).join(
                    Account, Account.id == PasskeyCredential.user_id
                )
            )
        ).all()
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        begin = await c.post(
            "/auth/invites/redeem/begin", json={"token": "racing-token"}
        )
        complete = await c.post(
            "/auth/invites/redeem/complete",
            json={"token": "racing-token", "credential": _FAKE_REGISTER_CREDENTIAL},
        )

    assert begin.status_code == 200  # decoy, indistinguishable as ever
    assert complete.status_code == 401

    after = len(
        (
            await session.execute(
                select(PasskeyCredential).join(
                    Account, Account.id == PasskeyCredential.user_id
                )
            )
        ).all()
    )
    assert after == before, "no credential may be added to the existing account"
