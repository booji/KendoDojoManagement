"""
Unit/integration tests for issue #45 — Admin Personal Settings parity.

Uses StubRepository pattern — NO real DB.

Acceptance criteria covered here (criteria 1-5):
  1. GET /users/me/member returns 200 for an admin user with a linked member record.
  2. PUT /users/me/member creates a new Member record for an admin and returns it correctly.
  3. PUT /users/me/member updates an existing Member record for an admin.
  4. The created Member record appears in GET /members (admin list endpoint).
  5. An admin cannot use PUT /users/me/member to set admin-only fields
     (e.g. is_coach, membership_status).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from app.members.dependencies import get_member_repo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN_SUB = "admin-uuid-settings"

_ADMIN_CLAIMS = UserClaims(
    sub=_ADMIN_SUB, email="admin@dojo.test", role="admin", is_active=True
)


def _admin_override():
    return _ADMIN_CLAIMS


def _seed_admin_member(**overrides) -> dict[str, Any]:
    base: dict[str, Any] = {
        "email": "admin@dojo.test",
        "first_name": "Admin",
        "surname": "User",
        "display_name": None,
        "dob": "1985-03-10",
        "join_date": "2020-01-01",
        "membership_status": "active",
        "is_coach": False,
        "is_first_aider": False,
        "emergency_contact_name": "Admin Contact",
        "emergency_contact_phone": "+447700900002",
        "user_id": _ADMIN_SUB,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Stub repository (same shape as in test_member_self_update.py)
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
                if term in r["first_name"].lower()
                or term in r["surname"].lower()
                or term in r["email"].lower()
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
# AC1 — GET /users/me/member returns 200 for an admin with a linked record
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_get_my_member_returns_200_with_linked_record(member_repo) -> None:
    """An admin with a linked Member record gets 200 from GET /users/me/member."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/member")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "admin@dojo.test"
    assert body["first_name"] == "Admin"
    assert body["surname"] == "User"
    assert "id" in body


@pytest.mark.anyio
async def test_admin_get_my_member_returns_404_when_no_linked_record(
    member_repo,
) -> None:
    """An admin without a linked Member record gets 404."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/member")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC2 — PUT /users/me/member creates a new Member record for an admin
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_put_my_member_creates_record_when_none_exists(member_repo) -> None:
    """PUT /users/me/member creates a Member record for an admin with no existing record."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={
                "first_name": "New Admin",
                "surname": "Member",
                "dob": "1985-03-10",
                "emergency_contact_name": "Admin Emergency",
                "emergency_contact_phone": "+447700900002",
            },
        )

    assert response.status_code in (200, 201)
    body = response.json()
    assert "id" in body
    assert body["first_name"] == "New Admin"
    assert body["surname"] == "Member"


@pytest.mark.anyio
async def test_admin_put_my_member_created_record_is_retrievable(member_repo) -> None:
    """A Member record created by an admin via PUT is immediately retrievable via GET."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        put_resp = await c.put(
            "/users/me/member",
            json={
                "first_name": "Retrievable",
                "surname": "Admin",
                "dob": "1980-07-04",
            },
        )

    assert put_resp.status_code in (200, 201)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        get_response = await c.get("/users/me/member")

    assert get_response.status_code == 200
    assert get_response.json()["first_name"] == "Retrievable"
    assert get_response.json()["surname"] == "Admin"


# ---------------------------------------------------------------------------
# AC3 — PUT /users/me/member updates an existing Member record for an admin
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_put_my_member_updates_existing_record(member_repo) -> None:
    """PUT /users/me/member updates an existing Member record for an admin."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"first_name": "Updated Admin"},
        )

    assert response.status_code == 200
    assert response.json()["first_name"] == "Updated Admin"


@pytest.mark.anyio
async def test_admin_put_my_member_update_persists_to_get(member_repo) -> None:
    """Admin update via PUT is visible in a subsequent GET."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.put("/users/me/member", json={"first_name": "Updated Admin"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        get_response = await c.get("/users/me/member")

    assert get_response.status_code == 200
    assert get_response.json()["first_name"] == "Updated Admin"


# ---------------------------------------------------------------------------
# AC4 — Created Member record appears in GET /members (admin list endpoint)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_created_member_record_appears_in_members_list(member_repo) -> None:
    """A Member record created via PUT /users/me/member appears in GET /members."""
    # Set up both guards: admin can create their own member record AND list members
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        put_resp = await c.put(
            "/users/me/member",
            json={
                "first_name": "Listed Admin",
                "surname": "Member",
                "dob": "1975-11-22",
            },
        )

    assert put_resp.status_code in (200, 201)
    created_id = put_resp.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        list_resp = await c.get("/members")

    assert list_resp.status_code == 200
    member_ids = [m["id"] for m in list_resp.json()]
    assert created_id in member_ids


@pytest.mark.anyio
async def test_admin_member_record_email_matches_admin_email_in_list(
    member_repo,
) -> None:
    """The admin's Member record in GET /members has the admin's email."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.put(
            "/users/me/member",
            json={
                "first_name": "Admin In",
                "surname": "List",
                "dob": "1970-01-15",
            },
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        list_resp = await c.get("/members")

    assert list_resp.status_code == 200
    emails = [m["email"] for m in list_resp.json()]
    assert "admin@dojo.test" in emails


# ---------------------------------------------------------------------------
# AC5 — Admin cannot use PUT /users/me/member to set admin-only fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_put_my_member_cannot_set_is_coach(member_repo) -> None:
    """is_coach sent via PUT /users/me/member must not be applied, even for admins."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member(is_coach=False))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"is_coach": True},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["is_coach"] is False


@pytest.mark.anyio
async def test_admin_put_my_member_cannot_set_membership_status(member_repo) -> None:
    """membership_status sent via PUT /users/me/member must not be applied, even for admins."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member(membership_status="active"))

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
async def test_admin_put_my_member_cannot_set_is_first_aider(member_repo) -> None:
    """is_first_aider sent via PUT /users/me/member must not be applied, even for admins."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member(is_first_aider=False))

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
