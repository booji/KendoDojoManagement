"""
Unit tests for issue #147 — Admin global pending grade queue.

GET /grades/pending returns all pending entries across all members,
each enriched with a member_name field.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. Admin gets all pending entries across multiple members, each including member_name
  2. Non-admin (member role) gets 403
  3. Unauthenticated gets 401 or 403
  4. Returns empty list (not error) when no pending entries
  5. Only returns pending entries, not confirmed ones
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN
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

# Valid UUIDs for use in URL path params
_MEMBER_A_ID = "00000000-0000-0000-0000-000000000001"
_MEMBER_B_ID = "00000000-0000-0000-0000-000000000002"


def _admin_override() -> AccountClaims:
    return _ADMIN


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

_MEMBER_A_RECORD: dict[str, Any] = {
    "id": _MEMBER_A_ID,
    "email": "member-a@dojo.test",
    "first_name": "Alice",
    "surname": "Kendo",
    "user_id": _MEMBER_A.sub,
    "membership_status": "active",
}

_MEMBER_B_RECORD: dict[str, Any] = {
    "id": _MEMBER_B_ID,
    "email": "member-b@dojo.test",
    "first_name": "Bob",
    "surname": "Kendo",
    "user_id": "member-b-uuid",
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
    repo = InMemoryMemberRepository([_MEMBER_A_RECORD, _MEMBER_B_RECORD])
    app.dependency_overrides[get_member_repo] = lambda: repo
    return repo


@pytest.fixture()
def grade_repo() -> InMemoryGradeRepository:
    repo = InMemoryGradeRepository(
        member_names={_MEMBER_A_ID: "Alice Kendo", _MEMBER_B_ID: "Bob Kendo"}
    )
    app.dependency_overrides[get_grade_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — Admin gets all pending entries across multiple members with member_name
# ---------------------------------------------------------------------------


async def test_admin_gets_pending_entries_across_members(
    member_repo, grade_repo
) -> None:
    """AC1: GET /grades/pending returns all pending entries from all members,
    each including a member_name field."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # Member A has a pending SHODAN
    await grade_repo.add_promotion(
        member_id=_MEMBER_A_ID,
        grade="SHODAN",
        display_name="Shodan (1-dan)",
        assigned_by=None,
        promoted_at="2025-01-10T10:00:00+00:00",
        status="pending",
    )
    # Member B has a pending NIDAN
    await grade_repo.add_promotion(
        member_id=_MEMBER_B_ID,
        grade="NIDAN",
        display_name="Nidan (2-dan)",
        assigned_by=None,
        promoted_at="2025-01-12T10:00:00+00:00",
        status="pending",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/grades/pending")

    assert response.status_code == 200, (
        f"Expected 200 OK, got {response.status_code}: {response.text}"
    )
    items = response.json()
    assert len(items) == 2, f"Expected 2 pending entries, got {len(items)}: {items}"

    grades = {item["grade"] for item in items}
    assert "SHODAN" in grades
    assert "NIDAN" in grades

    # Every entry must include member_name
    for item in items:
        assert "member_name" in item, (
            f"Each pending entry must include member_name; got keys: {list(item.keys())}"
        )
        assert item["member_name"] in (
            "Alice Kendo",
            "Bob Kendo",
        ), f"Unexpected member_name: {item['member_name']}"

    # Validate required response fields
    required_fields = {
        "id",
        "member_id",
        "member_name",
        "grade",
        "display_name",
        "status",
    }
    for item in items:
        missing = required_fields - set(item.keys())
        assert not missing, f"Missing fields in response: {missing}"


async def test_pending_response_includes_promoted_at(member_repo, grade_repo) -> None:
    """AC1: Each pending entry includes promoted_at (or null when not provided)."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    await grade_repo.add_promotion(
        member_id=_MEMBER_A_ID,
        grade="SHODAN",
        display_name="Shodan (1-dan)",
        assigned_by=None,
        promoted_at="2025-03-01T00:00:00+00:00",
        status="pending",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/grades/pending")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert "promoted_at" in items[0], "Response must include promoted_at field"


# ---------------------------------------------------------------------------
# AC2 — Non-admin gets 403
# ---------------------------------------------------------------------------


async def test_non_admin_member_gets_403(member_repo, grade_repo, cookies_for) -> None:
    """AC2: A non-admin member calling GET /grades/pending receives 403.

    No REQUIRE_ADMIN override is set, so the real guard fires against a real
    member token — overriding the guard here would test nothing.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api",
        cookies=cookies_for(_MEMBER_A),
    ) as c:
        response = await c.get("/grades/pending")

    assert response.status_code in (
        401,
        403,
    ), f"Non-admin must be rejected; got {response.status_code}"


# ---------------------------------------------------------------------------
# AC3 — Unauthenticated gets 401 or 403
# ---------------------------------------------------------------------------


async def test_unauthenticated_gets_401_or_403(member_repo, grade_repo) -> None:
    """AC3: Unauthenticated request to GET /grades/pending returns 401 or 403.

    No REQUIRE_ADMIN override is set, so the real guard fires.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/grades/pending")

    assert response.status_code in (
        401,
        403,
    ), f"Unauthenticated request must be rejected; got {response.status_code}"


# ---------------------------------------------------------------------------
# AC4 — Returns empty list when no pending entries
# ---------------------------------------------------------------------------


async def test_empty_list_when_no_pending_entries(member_repo, grade_repo) -> None:
    """AC4: GET /grades/pending returns [] (not an error) when no pending entries exist."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # Seed only a confirmed entry — no pending ones
    await grade_repo.add_promotion(
        member_id=_MEMBER_A_ID,
        grade="SHODAN",
        display_name="Shodan (1-dan)",
        assigned_by="admin-uuid",
        promoted_at="2025-01-01T10:00:00+00:00",
        status="confirmed",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/grades/pending")

    assert response.status_code == 200, (
        f"Empty queue must return 200, not an error; got {response.status_code}"
    )
    items = response.json()
    assert items == [], f"Expected empty list, got {items}"


async def test_empty_list_when_no_entries_at_all(member_repo, grade_repo) -> None:
    """AC4: GET /grades/pending returns [] when there are no grade entries at all."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/grades/pending")

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# AC5 — Only pending entries returned, not confirmed ones
# ---------------------------------------------------------------------------


async def test_only_pending_entries_returned(member_repo, grade_repo) -> None:
    """AC5: GET /grades/pending filters to only status==pending; confirmed excluded."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # One confirmed and one pending for the same member
    await grade_repo.add_promotion(
        member_id=_MEMBER_A_ID,
        grade="SHODAN",
        display_name="Shodan (1-dan)",
        assigned_by="admin-uuid",
        promoted_at="2024-06-01T10:00:00+00:00",
        status="confirmed",
    )
    await grade_repo.add_promotion(
        member_id=_MEMBER_A_ID,
        grade="NIDAN",
        display_name="Nidan (2-dan)",
        assigned_by=None,
        promoted_at="2025-01-15T10:00:00+00:00",
        status="pending",
    )
    # Member B also has a confirmed entry — must be excluded
    await grade_repo.add_promotion(
        member_id=_MEMBER_B_ID,
        grade="ROKKYUU",
        display_name="Rokkyū (6-kyu)",
        assigned_by="admin-uuid",
        promoted_at="2024-01-01T10:00:00+00:00",
        status="confirmed",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/grades/pending")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1, (
        f"Only pending entries should be returned; got {len(items)}: {items}"
    )
    assert items[0]["grade"] == "NIDAN"
    assert items[0]["status"] == "pending"
    # Confirmed entries must not appear
    returned_grades = {item["grade"] for item in items}
    assert "SHODAN" not in returned_grades, (
        "Confirmed SHODAN must not appear in pending queue"
    )
    assert "ROKKYUU" not in returned_grades, "Confirmed ROKKYUU must not appear"
