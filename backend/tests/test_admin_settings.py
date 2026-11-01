"""
Unit/integration tests for issue #45 — Admin Personal Settings parity.

Uses StubRepository pattern — NO real DB.

Acceptance criteria covered here:
  1. GET /accounts/me/member returns 200 for an admin user with a linked member record.
  3. PUT /accounts/me/member updates an existing Member record for an admin.
  5. An admin cannot use PUT /accounts/me/member to set admin-only fields
     (e.g. is_coach, membership_status).

Criteria 2 and 4 (an admin's PUT creating their Member, which then appears in
GET /members) went with #432: the first Admin's Member is created at the setup
claim, so there is no record left for onboarding to create.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.main import app
from app.members.dependencies import get_member_repo
from tests.fake_repositories import InMemoryMemberRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN_SUB = "admin-uuid-settings"

_ADMIN_CLAIMS = AccountClaims(sub=_ADMIN_SUB, email="admin@dojo.test", role="admin")


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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def member_repo() -> InMemoryMemberRepository:
    repo = InMemoryMemberRepository()
    app.dependency_overrides[get_member_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — GET /accounts/me/member returns 200 for an admin with a linked record
# ---------------------------------------------------------------------------


async def test_admin_get_my_member_returns_200_with_linked_record(member_repo) -> None:
    """An admin with a linked Member record gets 200 from GET /accounts/me/member."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/accounts/me/member")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "admin@dojo.test"
    assert body["first_name"] == "Admin"
    assert body["surname"] == "User"
    assert "id" in body


async def test_admin_get_my_member_returns_404_when_no_linked_record(
    member_repo,
) -> None:
    """An admin without a linked Member record gets 404."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/accounts/me/member")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC3 — PUT /accounts/me/member updates an existing Member record for an admin
# ---------------------------------------------------------------------------


async def test_admin_put_my_member_updates_existing_record(member_repo) -> None:
    """PUT /accounts/me/member updates an existing Member record for an admin."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"first_name": "Updated Admin"},
        )

    assert response.status_code == 200
    assert response.json()["first_name"] == "Updated Admin"


async def test_admin_put_my_member_update_persists_to_get(member_repo) -> None:
    """Admin update via PUT is visible in a subsequent GET."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.put("/accounts/me/member", json={"first_name": "Updated Admin"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        get_response = await c.get("/accounts/me/member")

    assert get_response.status_code == 200
    assert get_response.json()["first_name"] == "Updated Admin"


# ---------------------------------------------------------------------------
# AC5 — Admin cannot use PUT /accounts/me/member to set admin-only fields
# ---------------------------------------------------------------------------


async def test_admin_put_my_member_cannot_set_is_coach(member_repo) -> None:
    """is_coach sent via PUT /accounts/me/member must not be applied, even for admins."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member(is_coach=False))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"is_coach": True},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["is_coach"] is False


async def test_admin_put_my_member_cannot_set_membership_status(member_repo) -> None:
    """membership_status sent via PUT /accounts/me/member must not be applied, even for admins."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member(membership_status="active"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"membership_status": "inactive"},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["membership_status"] == "active"


async def test_admin_put_my_member_cannot_set_is_first_aider(member_repo) -> None:
    """is_first_aider sent via PUT /accounts/me/member must not be applied, even for admins."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    await member_repo.add(_seed_admin_member(is_first_aider=False))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"is_first_aider": True},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["is_first_aider"] is False
