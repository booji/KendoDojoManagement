"""
Unit tests for issue #146 — Admin approve/reject pending grade submissions.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. POST /members/{id}/grades/{entry_id}/approve → pending entry becomes confirmed,
     assigned_by set from auth token
  2. Approve non-existent entry → 404; approve already-confirmed entry → 409
  3. DELETE /members/{id}/grades/{entry_id} → 204 (pending entry removed)
  4. Delete confirmed entry → 409
  5. Non-admin caller → 403 for both endpoints
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.schemas import AccountClaims
from app.grades.dependencies import get_grade_repo
from app.main import app
from app.members.dependencies import get_member_repo
from tests.fake_repositories import InMemoryGradeRepository, InMemoryMemberRepository

# ---------------------------------------------------------------------------
# Auth claim helpers
# ---------------------------------------------------------------------------

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER_A = AccountClaims(
    sub="member-a-uuid", email="member-a@dojo.test", role="member"
)

_MEMBER_A_ID = "00000000-0000-0000-0000-000000000001"

_PENDING_ENTRY_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_CONFIRMED_ENTRY_ID = "bbbbbbbb-0000-0000-0000-000000000002"


def _admin_override():
    return _ADMIN


def _member_a_override():
    return _MEMBER_A


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

_MEMBER_A_RECORD: dict[str, Any] = {
    "id": _MEMBER_A_ID,
    "email": "member-a@dojo.test",
    "first_name": "Member",
    "surname": "A",
    "user_id": _MEMBER_A.sub,
    "membership_status": "active",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def member_repo() -> InMemoryMemberRepository:
    repo = InMemoryMemberRepository([_MEMBER_A_RECORD])
    app.dependency_overrides[get_member_repo] = lambda: repo
    return repo


@pytest.fixture()
def grade_repo() -> InMemoryGradeRepository:
    repo = InMemoryGradeRepository(
        [
            {
                "id": _PENDING_ENTRY_ID,
                "member_id": _MEMBER_A_ID,
                "grade": "SHODAN",
                "display_name": "Shodan (1-dan)",
                "assigned_by": None,
                "promoted_at": "2025-01-01T10:00:00+00:00",
                "status": "pending",
            },
            {
                "id": _CONFIRMED_ENTRY_ID,
                "member_id": _MEMBER_A_ID,
                "grade": "ROKKYUU",
                "display_name": "Rokkyū (6-kyu)",
                "assigned_by": "admin-uuid",
                "promoted_at": "2024-01-01T10:00:00+00:00",
                "status": "confirmed",
            },
        ]
    )
    app.dependency_overrides[get_grade_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — POST approve transitions pending → confirmed, sets assigned_by
# ---------------------------------------------------------------------------


async def test_approve_pending_entry_returns_200_and_confirmed_status(
    member_repo, grade_repo
) -> None:
    """AC1: POST approve on a pending entry → 200, status==confirmed."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/grades/{entry_id}/approve")

    assert response.status_code == 200, (
        f"Expected 200 OK, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["status"] == "confirmed", (
        f"Entry status must be 'confirmed' after approval; got {body.get('status')!r}"
    )


async def test_approve_sets_assigned_by_from_auth_token(
    member_repo, grade_repo
) -> None:
    """AC1: approved entry's assigned_by must equal the admin's sub from the token."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/grades/{entry_id}/approve")

    assert response.status_code == 200, (
        f"Expected 200 OK, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("assigned_by") == _ADMIN.sub, (
        f"assigned_by must be set to the approving admin's sub; got {body.get('assigned_by')!r}"
    )


# ---------------------------------------------------------------------------
# AC2 — approve 404 / 409
# ---------------------------------------------------------------------------


async def test_approve_nonexistent_entry_returns_404(member_repo, grade_repo) -> None:
    """AC2: Approving an entry that doesn't exist → 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    nonexistent_id = "99999999-0000-0000-0000-000000000000"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/grades/{nonexistent_id}/approve")

    assert response.status_code == 404, (
        f"Expected 404 Not Found, got {response.status_code}: {response.text}"
    )


async def test_approve_already_confirmed_entry_returns_409(
    member_repo, grade_repo
) -> None:
    """AC2: Approving an entry that is already confirmed → 409."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _CONFIRMED_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/grades/{entry_id}/approve")

    assert response.status_code == 409, (
        f"Expected 409 Conflict for already-confirmed entry, got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# AC3 — DELETE pending entry → 204
# ---------------------------------------------------------------------------


async def test_delete_pending_entry_returns_204(member_repo, grade_repo) -> None:
    """AC3: DELETE on a pending entry → 204 No Content."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/members/{member_id}/grades/{entry_id}")

    assert response.status_code == 204, (
        f"Expected 204 No Content, got {response.status_code}: {response.text}"
    )


async def test_delete_pending_entry_removes_it_from_history(
    member_repo, grade_repo
) -> None:
    """AC3: After DELETE, the entry no longer appears in grade history."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        delete_resp = await c.delete(f"/members/{member_id}/grades/{entry_id}")
        assert delete_resp.status_code == 204

        history_resp = await c.get(f"/members/{member_id}/grades")

    assert history_resp.status_code == 200
    ids = [e["id"] for e in history_resp.json()]
    assert entry_id not in ids, "Deleted entry must not appear in grade history"


# ---------------------------------------------------------------------------
# AC4 — DELETE confirmed entry → 409
# ---------------------------------------------------------------------------


async def test_delete_confirmed_entry_returns_409(member_repo, grade_repo) -> None:
    """AC4: Attempting to delete a confirmed entry → 409 Conflict."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _CONFIRMED_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/members/{member_id}/grades/{entry_id}")

    assert response.status_code == 409, (
        f"Expected 409 Conflict when deleting confirmed entry, got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# AC5 — Non-admin callers → 403
# ---------------------------------------------------------------------------


async def test_approve_non_admin_returns_403(
    member_repo, grade_repo, cookies_for
) -> None:
    """AC5: Non-admin caller on POST approve → 403 Forbidden.

    No REQUIRE_ADMIN override is set, so the real guard fires against a real
    member token — overriding the guard here would test nothing.
    """
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api",
        cookies=cookies_for(_MEMBER_A),
    ) as c:
        response = await c.post(f"/members/{member_id}/grades/{entry_id}/approve")

    assert response.status_code == 403, (
        f"Non-admin must be rejected with 403; got {response.status_code}"
    )


async def test_delete_non_admin_returns_403(
    member_repo, grade_repo, cookies_for
) -> None:
    """AC5: Non-admin caller on DELETE → 403 Forbidden.

    No REQUIRE_ADMIN override is set, so the real guard fires against a real
    member token — overriding the guard here would test nothing.
    """
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api",
        cookies=cookies_for(_MEMBER_A),
    ) as c:
        response = await c.delete(f"/members/{member_id}/grades/{entry_id}")

    assert response.status_code == 403, (
        f"Non-admin must be rejected with 403; got {response.status_code}"
    )
