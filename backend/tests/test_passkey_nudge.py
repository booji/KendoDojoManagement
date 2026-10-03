"""Unit / integration tests for issue #40 — Second passkey nudge.

Backend concerns:
  1. POST /auth/register/passkey/complete response includes show_nudge: bool.
     - show_nudge=True when the user's passkey count went from 0→1.
     - show_nudge=False when the user already had ≥1 passkeys.
  2. GET /auth/security-status returns passkey_count so the frontend can
     show/hide the "You have 1 passkey — consider adding a backup" banner
     in Settings > Security.

Uses StubRepository pattern — NO real DB. Dependencies are overridden
via app.dependency_overrides to inject in-memory stubs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from tests.account_support import seed_account

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USER_A = UserClaims(
    sub="user-a-nudge-uuid", email="nudge-a@dojo.test", role="member", is_active=True
)


def _user_a_override():
    return _USER_A


# ---------------------------------------------------------------------------
# Stub passkey repository
# ---------------------------------------------------------------------------


class StubPasskeyRepo:
    """In-memory stand-in for a PasskeyCredential repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def _seed(
        self,
        user_id: str,
        *,
        label: str = "My Passkey",
        aaguid: str | None = None,
    ) -> dict[str, Any]:
        pk_id = str(uuid.uuid4())
        record: dict[str, Any] = {
            "id": pk_id,
            "user_id": user_id,
            "credential_id": b"fake-cred-id-" + pk_id.encode(),
            "public_key": b"fake-public-key",
            "label": label,
            "aaguid": aaguid,
            "sign_count": 0,
            "created_at": datetime.now(UTC),
            "last_used_at": None,
        }
        self._store[pk_id] = record
        return record

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return [r for r in self._store.values() if r["user_id"] == user_id]

    async def get(self, passkey_id: str) -> dict[str, Any] | None:
        return self._store.get(passkey_id)

    async def update_label(
        self, passkey_id: str, user_id: str, label: str
    ) -> dict[str, Any] | None:
        record = self._store.get(passkey_id)
        if record is None or record["user_id"] != user_id:
            return None
        record["label"] = label
        return record

    async def delete(self, passkey_id: str, user_id: str) -> bool:
        record = self._store.get(passkey_id)
        if record is None or record["user_id"] != user_id:
            return False
        del self._store[passkey_id]
        return True

    async def count_for_user(self, user_id: str) -> int:
        return sum(1 for r in self._store.values() if r["user_id"] == user_id)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def passkey_repo() -> StubPasskeyRepo:
    from app.auth.dependencies import get_passkey_repo

    repo = StubPasskeyRepo()
    app.dependency_overrides[get_passkey_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 (backend) — show_nudge=True when registering the first passkey (0→1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_passkey_complete_returns_show_nudge_true_for_first_passkey(
    passkey_repo, db_client
) -> None:
    """POST /auth/register/passkey/complete includes show_nudge=True when
    the user had zero passkeys before this registration.

    The frontend uses this flag to trigger the lockout-risk modal.
    """
    from sqlalchemy import insert

    from app.auth.db_models import PasskeyCredential

    session = db_client

    # A claimed instance: /auth/register/passkey/complete refuses to run while
    # no credential exists anywhere, because that is an unclaimed instance and
    # the first admin is claimed through the token-gated setup route
    # (ADR-0003, #402). This user still has none of its own, which is what
    # show_nudge is about.
    claimed_user_id = str(uuid.uuid4())
    await seed_account(session, f"claimed-{claimed_user_id}@dojo.test", user_id=claimed_user_id, role="admin", is_active=True)
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=claimed_user_id,
            credential_id=uuid.uuid4().bytes,
            public_key=b"seeded-public-key",
            sign_count=0,
            created_at=datetime.now(UTC),
        )
    )

    # Seed a user with pending challenge and NO existing passkeys
    user_id = str(uuid.uuid4())
    await seed_account(session, "firstpasskey@dojo.test", user_id=user_id, role="member", is_active=True, pending_challenge="dGVzdC1jaGFsbGVuZ2U", challenge_issued_at=datetime.now(UTC))
    await session.flush()

    mock_verified = MagicMock()
    mock_verified.credential_id = b"test-cred-id-nudge-true"
    mock_verified.credential_public_key = b"test-public-key"
    mock_verified.sign_count = 0
    mock_verified.aaguid = None

    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/auth/register/passkey/complete",
                json={
                    "email": "firstpasskey@dojo.test",
                    "credential": {
                        "id": "dGVzdC1jcmVkLW51ZGdlLXRydWU",
                        "rawId": "dGVzdC1jcmVkLW51ZGdlLXRydWU",
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
    # The response must include show_nudge=True because this was the first passkey
    assert "show_nudge" in body, (
        "POST /auth/register/passkey/complete must return show_nudge in the response body"
    )
    assert body["show_nudge"] is True, (
        f"show_nudge should be True when registering first passkey, got {body['show_nudge']!r}"
    )


# ---------------------------------------------------------------------------
# AC2 (backend) — show_nudge=False when registering a subsequent passkey (≥1→n)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_passkey_complete_returns_show_nudge_false_for_subsequent_passkey(
    passkey_repo, db_client
) -> None:
    """POST /auth/register/passkey/complete includes show_nudge=False when
    the user already had one or more passkeys before this registration.

    The modal must only fire on the 0→1 transition.
    """
    from sqlalchemy import insert

    from app.auth.db_models import PasskeyCredential

    session = db_client

    user_id = str(uuid.uuid4())
    # Seed a user with an existing passkey (count=1 before this registration)
    await seed_account(session, "secondpasskey@dojo.test", user_id=user_id, role="member", is_active=True, pending_challenge="dGVzdC1jaGFsbGVuZ2U", challenge_issued_at=datetime.now(UTC))
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_id=b"already-existing-cred",
            public_key=b"existing-public-key",
            sign_count=0,
        )
    )
    await session.flush()

    mock_verified = MagicMock()
    mock_verified.credential_id = b"second-cred-id-nudge-false"
    mock_verified.credential_public_key = b"second-public-key"
    mock_verified.sign_count = 0
    mock_verified.aaguid = None

    with patch("webauthn.verify_registration_response", return_value=mock_verified):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/auth/register/passkey/complete",
                json={
                    "email": "secondpasskey@dojo.test",
                    "credential": {
                        "id": "c2Vjb25kLWNyZWQtaWQtbnVkZ2UtZmFsc2U",
                        "rawId": "c2Vjb25kLWNyZWQtaWQtbnVkZ2UtZmFsc2U",
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
    assert "show_nudge" in body, (
        "POST /auth/register/passkey/complete must return show_nudge in the response body"
    )
    assert body["show_nudge"] is False, (
        f"show_nudge should be False when registering a subsequent passkey, got {body['show_nudge']!r}"
    )


# ---------------------------------------------------------------------------
# AC3/AC4 (backend) — GET /auth/security-status returns passkey_count
# ---------------------------------------------------------------------------


async def test_security_status_returns_passkey_count_zero(passkey_repo) -> None:
    """GET /auth/security-status returns passkey_count=0 for a user with no passkeys.

    The frontend uses this to hide the single-passkey banner in Settings > Security.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/security-status")

    assert response.status_code == 200, (
        f"GET /auth/security-status should return 200, got {response.status_code}"
    )
    body = response.json()
    assert "passkey_count" in body, (
        "GET /auth/security-status must include passkey_count in the response body"
    )
    assert body["passkey_count"] == 0


async def test_security_status_returns_passkey_count_one(passkey_repo) -> None:
    """GET /auth/security-status returns passkey_count=1 after the first passkey.

    passkey_count == 1 is the condition the frontend uses to show the banner:
    "You have 1 passkey — consider adding a backup".
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub, label="MacBook Touch ID")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/security-status")

    assert response.status_code == 200
    body = response.json()
    assert "passkey_count" in body, (
        "GET /auth/security-status must include passkey_count in the response body"
    )
    assert body["passkey_count"] == 1, (
        f"passkey_count should be 1 after one passkey is registered, got {body['passkey_count']!r}"
    )


async def test_security_status_returns_passkey_count_two(passkey_repo) -> None:
    """GET /auth/security-status returns passkey_count=2 when user has two passkeys.

    passkey_count >= 2 means the frontend must NOT show the single-passkey banner.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub, label="MacBook Touch ID")
    passkey_repo._seed(_USER_A.sub, label="iPhone Face ID")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/security-status")

    assert response.status_code == 200
    body = response.json()
    assert "passkey_count" in body, (
        "GET /auth/security-status must include passkey_count in the response body"
    )
    assert body["passkey_count"] == 2, (
        f"passkey_count should be 2 after two passkeys are registered, got {body['passkey_count']!r}"
    )


async def test_security_status_requires_authentication() -> None:
    """GET /auth/security-status returns 401 when no token is provided."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/security-status")
    assert response.status_code == 401, (
        f"GET /auth/security-status must require authentication, got {response.status_code}"
    )
