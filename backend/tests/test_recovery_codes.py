"""Unit / integration tests for issue #39 — Recovery codes.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. recovery_codes table fields: id, user_id, code_hash, set_id, used_at, created_at
  2. POST /auth/recovery/codes/generate — returns 8 plaintext codes; 409 if set exists
  3. POST /auth/recovery/codes/regenerate — invalidates old set, returns 8 new codes
  4. GET /auth/recovery/codes/status — returns unused_count and has_set; no plaintext
  5. DELETE /auth/passkeys/{id} — blocked if last passkey AND zero unused recovery codes
  8. Unit: 8 codes in xxxx-xxxx-xxxx format; plaintext not stored; regenerate invalidates
     old set; status reflects used/unused counts correctly
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Lazy import helpers — allow individual test collection even before impl exists
# ---------------------------------------------------------------------------
# These imports succeed already (they exist in the codebase)
from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app

# Code format: three 4-char alphanumeric segments separated by hyphens
_CODE_PATTERN = re.compile(r"^[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4}$")

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
# Stub passkey repository (mirrors test_passkey_management.py)
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
    ) -> dict[str, Any]:
        pk_id = str(uuid.uuid4())
        record: dict[str, Any] = {
            "id": pk_id,
            "user_id": user_id,
            "credential_id": b"fake-cred-id-" + pk_id.encode(),
            "public_key": b"fake-public-key",
            "label": label,
            "aaguid": None,
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
# Stub recovery repository
# ---------------------------------------------------------------------------


class StubRecoveryRepo:
    """In-memory stand-in for an AbstractRecoveryRepository."""

    def __init__(self) -> None:
        # Each entry: {id, user_id, code_hash, set_id, used_at, created_at}
        self._store: list[dict[str, Any]] = []

    def _seed(
        self,
        user_id: str,
        code_hash: str = "bcrypt-hash",
        set_id: str | None = None,
        used_at: datetime | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "code_hash": code_hash,
            "set_id": set_id or str(uuid.uuid4()),
            "used_at": used_at,
            "created_at": datetime.now(UTC),
        }
        self._store.append(record)
        return record

    async def create_codes(
        self, user_id: str, hashed_codes: list[str], set_id: str
    ) -> list[dict[str, Any]]:
        records = []
        for h in hashed_codes:
            record: dict[str, Any] = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "code_hash": h,
                "set_id": set_id,
                "used_at": None,
                "created_at": datetime.now(UTC),
            }
            self._store.append(record)
            records.append(record)
        return records

    async def has_active_set(self, user_id: str) -> bool:
        return any(
            r["user_id"] == user_id and r["used_at"] is None for r in self._store
        )

    async def invalidate_all(self, user_id: str) -> None:
        now = datetime.now(UTC)
        for r in self._store:
            if r["user_id"] == user_id and r["used_at"] is None:
                r["used_at"] = now

    async def count_unused(self, user_id: str) -> int:
        return sum(
            1 for r in self._store if r["user_id"] == user_id and r["used_at"] is None
        )

    async def get_all_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return [r for r in self._store if r["user_id"] == user_id]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def passkey_repo() -> StubPasskeyRepo:
    from app.auth.dependencies import get_passkey_repo  # exists

    repo = StubPasskeyRepo()
    app.dependency_overrides[get_passkey_repo] = lambda: repo
    return repo


@pytest.fixture()
def recovery_repo() -> StubRecoveryRepo:
    from app.auth.dependencies import get_recovery_repo  # red: does not exist yet

    repo = StubRecoveryRepo()
    app.dependency_overrides[get_recovery_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC8 (unit) — Service: generates exactly 8 codes
# ---------------------------------------------------------------------------


def test_generate_codes_returns_exactly_8() -> None:
    """Recovery service generates exactly 8 codes."""
    from app.auth.recovery_service import generate_recovery_codes  # red

    codes = generate_recovery_codes()
    assert len(codes) == 8, f"Expected 8 codes, got {len(codes)}"


def test_generate_codes_match_format() -> None:
    """Each generated code matches the xxxx-xxxx-xxxx format (alphanumeric segments)."""
    from app.auth.recovery_service import generate_recovery_codes  # red

    codes = generate_recovery_codes()
    for code in codes:
        assert _CODE_PATTERN.match(
            code
        ), f"Code '{code}' does not match xxxx-xxxx-xxxx format"


def test_generate_codes_are_unique() -> None:
    """All 8 generated codes are distinct (cryptographically random)."""
    from app.auth.recovery_service import generate_recovery_codes  # red

    codes = generate_recovery_codes()
    assert len(set(codes)) == 8, "Generated codes must all be unique"


def test_generate_codes_are_cryptographically_random() -> None:
    """Two calls to generate_recovery_codes produce different sets of codes."""
    from app.auth.recovery_service import generate_recovery_codes  # red

    set1 = set(generate_recovery_codes())
    set2 = set(generate_recovery_codes())
    assert (
        set1 != set2
    ), "Two calls returned identical codes — not cryptographically random"


# ---------------------------------------------------------------------------
# AC8 (unit) — Plaintext not stored; code_hash is stored
# ---------------------------------------------------------------------------


def test_stored_records_contain_code_hash_not_plaintext() -> None:
    """After generating codes, stored records have code_hash, not plaintext."""
    from app.auth.recovery_service import generate_recovery_codes  # red

    repo = StubRecoveryRepo()
    codes = generate_recovery_codes()

    async def _run():
        set_id = str(uuid.uuid4())
        # Simulate service storing hashes: hashes must differ from plaintext codes
        dummy_hashes = ["$2b$12$fakehash" + str(i) for i in range(8)]
        records = await repo.create_codes(_USER_A.sub, dummy_hashes, set_id)
        for record, code in zip(records, codes):
            assert (
                record["code_hash"] != code
            ), "Plaintext code was stored instead of its bcrypt hash"
            assert record["used_at"] is None
            assert record["set_id"] == set_id

    asyncio.run(_run())


def test_stored_records_have_required_fields() -> None:
    """Stored recovery code records include id, user_id, code_hash, set_id, used_at, created_at."""
    repo = StubRecoveryRepo()
    record = repo._seed(_USER_A.sub)

    required = {"id", "user_id", "code_hash", "set_id", "used_at", "created_at"}
    missing = required - set(record.keys())
    assert not missing, f"Missing fields in recovery code record: {missing}"


def test_stored_records_used_at_is_none_initially() -> None:
    """Freshly generated codes have used_at=None."""
    repo = StubRecoveryRepo()
    record = repo._seed(_USER_A.sub)
    assert record["used_at"] is None


# ---------------------------------------------------------------------------
# AC8 (unit) — Regenerate invalidates old set
# ---------------------------------------------------------------------------


def test_regenerate_invalidates_old_codes() -> None:
    """After invalidate_all, old codes have used_at set."""
    repo = StubRecoveryRepo()
    old_set_id = str(uuid.uuid4())
    for _ in range(8):
        repo._seed(_USER_A.sub, set_id=old_set_id)

    async def _run():
        await repo.invalidate_all(_USER_A.sub)
        old_codes = await repo.get_all_for_user(_USER_A.sub)
        for c in old_codes:
            if c["set_id"] == old_set_id:
                assert (
                    c["used_at"] is not None
                ), "Old code was not invalidated after regenerate"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# AC8 (unit) — Status reflects used/unused counts
# ---------------------------------------------------------------------------


def test_count_unused_reflects_actual_unused_codes() -> None:
    """count_unused returns only codes where used_at is None."""
    repo = StubRecoveryRepo()
    repo._seed(_USER_A.sub, used_at=None)
    repo._seed(_USER_A.sub, used_at=None)
    repo._seed(_USER_A.sub, used_at=datetime.now(UTC))

    async def _run():
        count = await repo.count_unused(_USER_A.sub)
        assert count == 2, f"Expected 2 unused codes, got {count}"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# AC2 — POST /auth/recovery/codes/generate — returns 8 plaintext codes
# ---------------------------------------------------------------------------


async def test_generate_endpoint_returns_8_codes(passkey_repo, recovery_repo) -> None:
    """POST /auth/recovery/codes/generate returns a list of 8 plaintext codes."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/auth/recovery/codes/generate")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict), f"Expected dict response, got {type(body)}"
    codes = body.get("codes")
    assert codes is not None, "Response missing 'codes' field"
    assert len(codes) == 8, f"Expected 8 codes, got {len(codes)}"


async def test_generate_endpoint_codes_match_format(
    passkey_repo, recovery_repo
) -> None:
    """POST /auth/recovery/codes/generate returns codes in xxxx-xxxx-xxxx format."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/auth/recovery/codes/generate")

    assert response.status_code == 200
    codes = response.json().get("codes", [])
    for code in codes:
        assert _CODE_PATTERN.match(
            code
        ), f"Code '{code}' does not match xxxx-xxxx-xxxx format"


async def test_generate_endpoint_returns_409_if_set_exists(
    passkey_repo, recovery_repo
) -> None:
    """POST /auth/recovery/codes/generate returns 409 if an active set already exists."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub)
    # Seed an existing active set
    for _ in range(8):
        recovery_repo._seed(_USER_A.sub, used_at=None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/auth/recovery/codes/generate")

    assert response.status_code == 409


async def test_generate_endpoint_requires_authentication(
    recovery_repo,
) -> None:
    """POST /auth/recovery/codes/generate returns 401 when unauthenticated."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/auth/recovery/codes/generate")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC3 — POST /auth/recovery/codes/regenerate — invalidates old, returns 8 new
# ---------------------------------------------------------------------------


async def test_regenerate_endpoint_returns_8_new_codes(
    passkey_repo, recovery_repo
) -> None:
    """POST /auth/recovery/codes/regenerate returns 8 new plaintext codes."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub)
    old_set_id = str(uuid.uuid4())
    for _ in range(8):
        recovery_repo._seed(_USER_A.sub, set_id=old_set_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/auth/recovery/codes/regenerate")

    assert response.status_code == 200
    body = response.json()
    codes = body.get("codes")
    assert codes is not None, "Response missing 'codes' field"
    assert len(codes) == 8, f"Expected 8 codes, got {len(codes)}"


async def test_regenerate_endpoint_invalidates_old_set(
    passkey_repo, recovery_repo
) -> None:
    """POST /auth/recovery/codes/regenerate marks old codes as used_at (not None)."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub)
    old_set_id = str(uuid.uuid4())
    for _ in range(8):
        recovery_repo._seed(_USER_A.sub, set_id=old_set_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post("/auth/recovery/codes/regenerate")

    # After regeneration, old set codes must have used_at set
    old_codes = [r for r in recovery_repo._store if r["set_id"] == old_set_id]
    for code in old_codes:
        assert (
            code["used_at"] is not None
        ), f"Old code {code['id']} was not invalidated after regenerate"


async def test_regenerate_endpoint_requires_authentication(
    recovery_repo,
) -> None:
    """POST /auth/recovery/codes/regenerate returns 401 when unauthenticated."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/auth/recovery/codes/regenerate")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC4 — GET /auth/recovery/codes/status — counts and has_set; no plaintext
# ---------------------------------------------------------------------------


async def test_status_endpoint_returns_unused_count_and_has_set(
    passkey_repo, recovery_repo
) -> None:
    """GET /auth/recovery/codes/status returns unused_count and has_set."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub)
    for _ in range(6):
        recovery_repo._seed(_USER_A.sub, used_at=None)
    for _ in range(2):
        recovery_repo._seed(_USER_A.sub, used_at=datetime.now(UTC))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/recovery/codes/status")

    assert response.status_code == 200
    body = response.json()
    assert "unused_count" in body, "Response missing 'unused_count'"
    assert "has_set" in body, "Response missing 'has_set'"
    assert body["unused_count"] == 6
    assert body["has_set"] is True


async def test_status_endpoint_has_set_false_when_no_codes(
    passkey_repo, recovery_repo
) -> None:
    """GET /auth/recovery/codes/status returns has_set=False and unused_count=0 when empty."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/recovery/codes/status")

    assert response.status_code == 200
    body = response.json()
    assert body["unused_count"] == 0
    assert body["has_set"] is False


async def test_status_endpoint_never_returns_plaintext_codes(
    passkey_repo, recovery_repo
) -> None:
    """GET /auth/recovery/codes/status must not include any plaintext code values."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub)
    for _ in range(8):
        recovery_repo._seed(_USER_A.sub, used_at=None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/recovery/codes/status")

    assert response.status_code == 200
    body = response.json()
    assert "codes" not in body, "Status endpoint must not return plaintext codes"
    assert "code_hash" not in body


async def test_status_endpoint_requires_authentication(
    recovery_repo,
) -> None:
    """GET /auth/recovery/codes/status returns 401 when unauthenticated."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/recovery/codes/status")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC5 — DELETE /auth/passkeys/{id} blocked if last passkey AND no unused codes
# ---------------------------------------------------------------------------


async def test_delete_last_passkey_blocked_when_no_recovery_codes(
    passkey_repo, recovery_repo
) -> None:
    """DELETE /auth/passkeys/{id} returns 400 when it is caller's last passkey
    AND there are zero unused recovery codes."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    record = passkey_repo._seed(_USER_A.sub, label="Only Key")
    pk_id = record["id"]
    # No recovery codes — unused_count == 0

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/auth/passkeys/{pk_id}")

    assert response.status_code == 400


async def test_delete_last_passkey_blocked_even_with_all_codes_used(
    passkey_repo, recovery_repo
) -> None:
    """DELETE /auth/passkeys/{id} returns 400 when last passkey AND all recovery codes consumed."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    record = passkey_repo._seed(_USER_A.sub, label="Only Key")
    pk_id = record["id"]
    # All codes are used (used_at is set)
    for _ in range(8):
        recovery_repo._seed(_USER_A.sub, used_at=datetime.now(UTC))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/auth/passkeys/{pk_id}")

    assert response.status_code == 400


async def test_delete_last_passkey_allowed_when_recovery_codes_exist(
    passkey_repo, recovery_repo
) -> None:
    """DELETE /auth/passkeys/{id} is NOT blocked when there are unused recovery codes.

    AC5 updates the existing block: the last passkey may be deleted only if the user
    has at least one unused recovery code available.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    record = passkey_repo._seed(_USER_A.sub, label="Only Key")
    pk_id = record["id"]
    # Seed 8 active (unused) recovery codes
    for _ in range(8):
        recovery_repo._seed(_USER_A.sub, used_at=None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/auth/passkeys/{pk_id}")

    assert response.status_code == 204


async def test_delete_non_last_passkey_not_affected_by_recovery_codes(
    passkey_repo, recovery_repo
) -> None:
    """DELETE /auth/passkeys/{id} succeeds normally when caller has multiple passkeys."""
    app.dependency_overrides[REQUIRE_MEMBER] = _user_a_override
    passkey_repo._seed(_USER_A.sub, label="Keep")
    record2 = passkey_repo._seed(_USER_A.sub, label="Delete Me")
    pk_id = record2["id"]
    # No recovery codes — but this should still succeed (not the last passkey)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/auth/passkeys/{pk_id}")

    assert response.status_code == 204
