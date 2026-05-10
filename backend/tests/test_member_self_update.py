"""
Unit tests for issue #25 — Member self-update API.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. GET /users/me/member returns caller's Member record (200) or 404 if none
  2. PUT /users/me/member updates allowed self-service fields, returns updated record
  3. Admin-only fields sent to PUT /users/me/member are rejected (422) or silently ignored
  4. PUT /users/me/member creates a new Member record if none linked (first-save onboarding)
  5. Both endpoints return 401 for unauthenticated requests
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from app.members.dependencies import get_member_repo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USER_SUB = "user-uuid-self"
_OTHER_SUB = "user-uuid-other"

_MEMBER_CLAIMS = UserClaims(
    sub=_USER_SUB, email="self@dojo.test", role="member", is_active=True
)


def _member_override():
    return _MEMBER_CLAIMS


def _seed_record(**overrides) -> dict[str, Any]:
    base: dict[str, Any] = {
        "email": "self@dojo.test",
        "full_name": "Self Member",
        "dob": "1990-06-15",
        "join_date": "2024-01-10",
        "membership_status": "active",
        "is_coach": False,
        "is_first_aider": False,
        "emergency_contact_name": "Emergency Contact",
        "emergency_contact_phone": "+447700900001",
        "parental_consent_obtained": False,
        "user_id": _USER_SUB,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Stub repository
# ---------------------------------------------------------------------------


class StubMemberRepo:
    """In-memory stand-in for a Member repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def get(self, member_id: str) -> dict[str, Any] | None:
        return self._store.get(member_id)

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        for item in self._store.values():
            if item["email"] == email:
                return item
        return None

    async def get_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        for item in self._store.values():
            if item.get("user_id") == user_id:
                return item
        return None

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        existing = await self.get_by_email(data["email"])
        if existing:
            raise ValueError(f"Member with email '{data['email']}' already exists")
        new_id = str(uuid.uuid4())
        record = {"id": new_id, **data}
        self._store[new_id] = record
        return record

    async def update(
        self, member_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        record = self._store.get(member_id)
        if record is None:
            return None
        record.update(data)
        return record

    async def deactivate(self, member_id: str) -> dict[str, Any] | None:
        record = self._store.get(member_id)
        if record is None:
            return None
        record["membership_status"] = "inactive"
        return record

    async def list(
        self,
        status: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        results = list(self._store.values())
        if status is not None:
            results = [r for r in results if r["membership_status"] == status]
        if search is not None:
            term = search.lower()
            results = [
                r
                for r in results
                if term in r["full_name"].lower() or term in r["email"].lower()
            ]
        return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def member_repo() -> StubMemberRepo:
    repo = StubMemberRepo()
    app.dependency_overrides[get_member_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — GET /users/me/member
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_my_member_returns_own_record(member_repo) -> None:
    """Happy path: authenticated member with a linked record gets 200."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/member")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "self@dojo.test"
    assert body["full_name"] == "Self Member"
    assert "id" in body


@pytest.mark.anyio
async def test_get_my_member_returns_404_when_no_linked_record(member_repo) -> None:
    """Member exists in auth but has no Member record yet."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/member")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_get_my_member_unauthenticated_returns_401(member_repo) -> None:
    """No credentials → 401."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/member")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_get_my_member_response_schema(member_repo) -> None:
    """Response includes all expected MemberResponse fields."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/member")

    assert response.status_code == 200
    body = response.json()
    expected_fields = {
        "id",
        "email",
        "full_name",
        "join_date",
        "membership_status",
        "is_coach",
        "is_first_aider",
        "emergency_contact_name",
        "emergency_contact_phone",
        "parental_consent_obtained",
        "is_minor",
    }
    for field in expected_fields:
        assert field in body, f"Missing field in response: {field}"


@pytest.mark.anyio
async def test_get_my_member_only_returns_own_record(member_repo) -> None:
    """Endpoint resolves by claims.sub, not a URL parameter."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    # Seed a record for another user — must not be returned
    await member_repo.add(_seed_record(email="other@dojo.test", user_id=_OTHER_SUB))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/member")

    # Caller has no linked record, should be 404
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC2 — PUT /users/me/member updates allowed fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_my_member_updates_full_name(member_repo) -> None:
    """PUT updates full_name and returns updated record."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"full_name": "Updated Self Name"},
        )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Updated Self Name"


@pytest.mark.anyio
async def test_put_my_member_updates_dob(member_repo) -> None:
    """PUT updates dob."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    new_dob = "1985-03-20"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"dob": new_dob},
        )

    assert response.status_code == 200
    # is_minor should be recalculated; record should reflect the new dob
    body = response.json()
    assert "is_minor" in body


@pytest.mark.anyio
async def test_put_my_member_updates_emergency_contact(member_repo) -> None:
    """PUT updates emergency contact fields."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={
                "emergency_contact_name": "New Emergency",
                "emergency_contact_phone": "+447700900999",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["emergency_contact_name"] == "New Emergency"
    assert body["emergency_contact_phone"] == "+447700900999"


@pytest.mark.anyio
async def test_put_my_member_update_persists(member_repo) -> None:
    """Change made via PUT is visible in subsequent GET."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.put("/users/me/member", json={"full_name": "Persisted Name"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        get_response = await c.get("/users/me/member")

    assert get_response.status_code == 200
    assert get_response.json()["full_name"] == "Persisted Name"


@pytest.mark.anyio
async def test_put_my_member_unauthenticated_returns_401(member_repo) -> None:
    """No credentials → 401."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"full_name": "Hacker"},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC3 — Admin-only fields must not be applied via PUT /users/me/member
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_my_member_admin_only_field_is_rejected_or_ignored(
    member_repo,
) -> None:
    """
    Sending is_coach (admin-only) via PUT /users/me/member must not apply the change.
    Either 422 (rejected) or 200 with the field unchanged are acceptable.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(is_coach=False))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"is_coach": True},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        # Field must NOT have been applied
        assert response.json()["is_coach"] is False


@pytest.mark.anyio
async def test_put_my_member_membership_status_is_rejected_or_ignored(
    member_repo,
) -> None:
    """
    Sending membership_status (admin-only) via PUT /users/me/member must not apply the change.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(membership_status="active"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"membership_status": "inactive"},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["membership_status"] == "active"


@pytest.mark.anyio
async def test_put_my_member_is_first_aider_is_rejected_or_ignored(member_repo) -> None:
    """is_first_aider is an admin-only field."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(is_first_aider=False))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"is_first_aider": True},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["is_first_aider"] is False


@pytest.mark.anyio
async def test_put_my_member_parental_consent_is_rejected_or_ignored(
    member_repo,
) -> None:
    """parental_consent_obtained is an admin-only field."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(parental_consent_obtained=False))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"parental_consent_obtained": True},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["parental_consent_obtained"] is False


# ---------------------------------------------------------------------------
# AC4 — PUT /users/me/member creates a new Member record if none exists
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_my_member_creates_record_when_none_exists(member_repo) -> None:
    """First-save onboarding: PUT creates a new Member linked to claims.sub."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={
                "full_name": "Brand New Member",
                "dob": "1995-08-22",
                "emergency_contact_name": "Parent",
                "emergency_contact_phone": "+447700900111",
            },
        )

    assert response.status_code in (200, 201)
    body = response.json()
    assert "id" in body
    assert body["full_name"] == "Brand New Member"


@pytest.mark.anyio
async def test_put_my_member_created_record_is_retrievable(member_repo) -> None:
    """A record created via PUT is immediately retrievable via GET."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.put(
            "/users/me/member",
            json={
                "full_name": "Onboarded Member",
                "dob": "1992-04-10",
            },
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        get_response = await c.get("/users/me/member")

    assert get_response.status_code == 200
    assert get_response.json()["full_name"] == "Onboarded Member"
