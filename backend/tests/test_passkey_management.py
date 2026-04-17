"""Unit / integration tests for issue #37 — Multi-passkey management.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. PasskeyCredential model fields: label, aaguid, created_at, last_used_at
  2. GET /auth/passkeys returns caller's passkeys (no public_key)
  3. PATCH /auth/passkeys/{id} updates label; 404 if not owned by caller
  4. DELETE /auth/passkeys/{id} removes passkey; 400 if last passkey
  5. Passkey registration auto-detects label from AAGUID
  7. JWT_EXPIRE_MINUTES default is 480
  8. Unit: list returns only caller's passkeys; label update persists;
     delete of last passkey returns 400; delete of non-owner returns 404
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USER_A = UserClaims(
    sub="user-a-uuid", email="usera@dojo.test", role="member", is_active=True
)
_USER_B = UserClaims(
    sub="user-b-uuid", email="userb@dojo.test", role="member", is_active=True
)


def _user_a_override():
    return _USER_A


def _user_b_override():
    return _USER_B


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
        created_at: datetime | None = None,
        last_used_at: datetime | None = None,
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
            "created_at": created_at or datetime.now(UTC),
            "last_used_at": last_used_at,
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
    from app.auth.dependencies import get_passkey_repo  # red: does not exist yet

    repo = StubPasskeyRepo()
    app.dependency_overrides[get_passkey_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — Model fields: label, aaguid, created_at, last_used_at
# ---------------------------------------------------------------------------


def test_passkey_credential_model_has_label_field() -> None:
    """PasskeyCredential must have a label column."""
    from app.auth.db_models import PasskeyCredential

    assert hasattr(
        PasskeyCredential, "label"
    ), "PasskeyCredential.label is missing — add it to the model"


def test_passkey_credential_model_has_aaguid_field() -> None:
    """PasskeyCredential must have an aaguid column (nullable)."""
    from app.auth.db_models import PasskeyCredential

    assert hasattr(
        PasskeyCredential, "aaguid"
    ), "PasskeyCredential.aaguid is missing — add it to the model"


def test_passkey_credential_model_has_created_at_field() -> None:
    """PasskeyCredential must have a created_at column."""
    from app.auth.db_models import PasskeyCredential

    assert hasattr(
        PasskeyCredential, "created_at"
    ), "PasskeyCredential.created_at is missing — add it to the model"


def test_passkey_credential_model_has_last_used_at_field() -> None:
    """PasskeyCredential must have a last_used_at column (nullable)."""
    from app.auth.db_models import PasskeyCredential

    assert hasattr(
        PasskeyCredential, "last_used_at"
    ), "PasskeyCredential.last_used_at is missing — add it to the model"


# ---------------------------------------------------------------------------
# AC7 — JWT_EXPIRE_MINUTES default is 480
# ---------------------------------------------------------------------------


def test_jwt_expire_minutes_default_is_480(monkeypatch) -> None:
    """JWT_EXPIRE_MINUTES must default to 480 (8 hours) when env var is absent."""
    import importlib

    monkeypatch.delenv("JWT_EXPIRE_MINUTES", raising=False)

    import app.config as cfg

    importlib.reload(cfg)
    assert (
        cfg.JWT_EXPIRE_MINUTES == 480
    ), f"Expected JWT_EXPIRE_MINUTES=480, got {cfg.JWT_EXPIRE_MINUTES}"


# ---------------------------------------------------------------------------
# AC2 — GET /auth/passkeys — list caller's passkeys
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_passkeys_returns_caller_passkeys_only(passkey_repo) -> None:
    """GET /auth/passkeys returns only passkeys belonging to the authenticated user."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override

    passkey_repo._seed(_USER_A.sub, label="Laptop Touch ID")
    passkey_repo._seed(_USER_A.sub, label="Phone Face ID")
    passkey_repo._seed(_USER_B.sub, label="Other user key")  # must NOT appear

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/passkeys")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    labels = {item["label"] for item in body}
    assert labels == {"Laptop Touch ID", "Phone Face ID"}


@pytest.mark.anyio
async def test_list_passkeys_response_fields(passkey_repo) -> None:
    """GET /auth/passkeys items include id, label, aaguid, created_at, last_used_at."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override

    passkey_repo._seed(
        _USER_A.sub,
        label="Security Key",
        aaguid="aaguid-value",
        last_used_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/passkeys")

    assert response.status_code == 200
    item = response.json()[0]
    assert "id" in item
    assert "label" in item
    assert "aaguid" in item
    assert "created_at" in item
    assert "last_used_at" in item


@pytest.mark.anyio
async def test_list_passkeys_never_returns_public_key(passkey_repo) -> None:
    """GET /auth/passkeys must never include public_key in the response."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/passkeys")

    assert response.status_code == 200
    for item in response.json():
        assert "public_key" not in item


@pytest.mark.anyio
async def test_list_passkeys_requires_authentication() -> None:
    """GET /auth/passkeys returns 401 when no token is provided."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/passkeys")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_list_passkeys_empty_for_new_user(passkey_repo) -> None:
    """GET /auth/passkeys returns an empty list when user has no passkeys."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/passkeys")

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# AC3 — PATCH /auth/passkeys/{id} — rename label
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_patch_passkey_label_succeeds(passkey_repo) -> None:
    """PATCH /auth/passkeys/{id} updates the label and returns the updated record."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    record = passkey_repo._seed(_USER_A.sub, label="Old Label")
    pk_id = record["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.patch(f"/auth/passkeys/{pk_id}", json={"label": "New Label"})

    assert response.status_code == 200
    assert response.json()["label"] == "New Label"


@pytest.mark.anyio
async def test_patch_passkey_label_is_persisted(passkey_repo) -> None:
    """After PATCH, a subsequent GET /auth/passkeys reflects the new label."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    record = passkey_repo._seed(_USER_A.sub, label="Original")
    pk_id = record["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.patch(f"/auth/passkeys/{pk_id}", json={"label": "Renamed"})
        list_resp = await c.get("/auth/passkeys")

    assert list_resp.status_code == 200
    labels = [item["label"] for item in list_resp.json()]
    assert "Renamed" in labels
    assert "Original" not in labels


@pytest.mark.anyio
async def test_patch_passkey_returns_404_for_non_owner(passkey_repo) -> None:
    """PATCH /auth/passkeys/{id} returns 404 when the passkey belongs to a different user."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    record = passkey_repo._seed(_USER_B.sub, label="User B Key")  # owned by B
    pk_id = record["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.patch(
            f"/auth/passkeys/{pk_id}", json={"label": "Stolen Label"}
        )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_patch_passkey_returns_404_for_unknown_id(passkey_repo) -> None:
    """PATCH /auth/passkeys/{id} returns 404 when the passkey id does not exist."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    random_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.patch(f"/auth/passkeys/{random_id}", json={"label": "Ghost"})

    assert response.status_code == 404


@pytest.mark.anyio
async def test_patch_passkey_requires_authentication() -> None:
    """PATCH /auth/passkeys/{id} returns 401 when no token is provided."""
    random_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.patch(f"/auth/passkeys/{random_id}", json={"label": "X"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC4 — DELETE /auth/passkeys/{id} — remove passkey
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_passkey_succeeds(passkey_repo) -> None:
    """DELETE /auth/passkeys/{id} removes the passkey when caller has more than one."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    record1 = passkey_repo._seed(_USER_A.sub, label="Keep")
    record2 = passkey_repo._seed(_USER_A.sub, label="Delete Me")
    pk_id = record2["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/auth/passkeys/{pk_id}")

    assert response.status_code == 204

    remaining = await passkey_repo.list_for_user(_USER_A.sub)
    assert len(remaining) == 1
    assert remaining[0]["id"] == record1["id"]


@pytest.mark.anyio
async def test_delete_last_passkey_returns_400(passkey_repo) -> None:
    """DELETE /auth/passkeys/{id} returns 400 when it is the caller's only passkey."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    record = passkey_repo._seed(_USER_A.sub, label="Only Key")
    pk_id = record["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/auth/passkeys/{pk_id}")

    assert response.status_code == 400


@pytest.mark.anyio
async def test_delete_passkey_returns_404_for_non_owner(passkey_repo) -> None:
    """DELETE /auth/passkeys/{id} returns 404 when passkey belongs to another user."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    record = passkey_repo._seed(_USER_B.sub, label="User B Key")
    pk_id = record["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/auth/passkeys/{pk_id}")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_delete_passkey_returns_404_for_unknown_id(passkey_repo) -> None:
    """DELETE /auth/passkeys/{id} returns 404 when the passkey id does not exist."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    random_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/auth/passkeys/{random_id}")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_delete_passkey_requires_authentication() -> None:
    """DELETE /auth/passkeys/{id} returns 401 when no token is provided."""
    random_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/auth/passkeys/{random_id}")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC5 — Passkey registration auto-detects label from AAGUID
# ---------------------------------------------------------------------------


def test_label_from_aaguid_returns_known_authenticator_name() -> None:
    """label_from_aaguid maps known AAGUIDs to human-readable names."""
    from app.auth.aaguid import label_from_aaguid  # red: does not exist yet

    # Windows Hello AAGUID (well-known)
    result = label_from_aaguid("6028b017-b1d4-4c02-b4b3-afcdafc96bb2")
    assert isinstance(result, str)
    assert len(result) > 0
    assert result != "6028b017-b1d4-4c02-b4b3-afcdafc96bb2"


def test_label_from_aaguid_returns_fallback_for_unknown() -> None:
    """label_from_aaguid returns a generic fallback for unrecognised AAGUIDs."""
    from app.auth.aaguid import label_from_aaguid  # red: does not exist yet

    result = label_from_aaguid("00000000-0000-0000-0000-000000000000")
    assert isinstance(result, str)
    assert len(result) > 0


def test_label_from_aaguid_returns_fallback_for_none() -> None:
    """label_from_aaguid handles None gracefully and returns a fallback."""
    from app.auth.aaguid import label_from_aaguid  # red: does not exist yet

    result = label_from_aaguid(None)
    assert isinstance(result, str)
    assert len(result) > 0
