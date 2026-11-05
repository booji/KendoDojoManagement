"""
Unit / integration tests for issue #8 — Grade promotion.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. Grade enum in strict order with machine value and display_name
  2. POST /members/{id}/promote advances grade by one step; rejects beyond Hachidan
  3. Each promotion records grade, date/timestamp, and admin member_id
  4. GET /members/{id}/grades returns full history chronological (oldest first)
  5. Grade history accessible by admin (any) and member (own only); 403 for other's
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.grades.dependencies import get_grade_repo  # noqa: F401 — will fail (red)
from app.grades.models import Grade  # noqa: F401 — will fail (red)
from app.main import app
from app.members.dependencies import get_member_repo  # noqa: F401 — will fail (red)
from tests.fake_repositories import InMemoryGradeRepository, InMemoryMemberRepository

# ---------------------------------------------------------------------------
# Auth claim helpers
# ---------------------------------------------------------------------------

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER_A = AccountClaims(
    sub="member-a-uuid", email="member-a@dojo.test", role="member"
)
_MEMBER_B = AccountClaims(
    sub="member-b-uuid", email="member-b@dojo.test", role="member"
)

# Valid UUIDs for use in URL path params (member record IDs, not user IDs)
_MEMBER_A_ID = "00000000-0000-0000-0000-000000000001"
_MEMBER_B_ID = "00000000-0000-0000-0000-000000000002"


def _admin_override():
    return _ADMIN


def _member_a_override():
    return _MEMBER_A


def _member_b_override():
    return _MEMBER_B


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

_MEMBER_B_RECORD: dict[str, Any] = {
    "id": _MEMBER_B_ID,
    "email": "member-b@dojo.test",
    "first_name": "Member",
    "surname": "B",
    "user_id": _MEMBER_B.sub,
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
    repo = InMemoryGradeRepository()
    app.dependency_overrides[get_grade_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — Grade enum order
# ---------------------------------------------------------------------------

EXPECTED_GRADE_ORDER = [
    "MUKYUU",
    "ROKKYUU",
    "GOKYUU",
    "YONKYUU",
    "SANKYUU",
    "NIKYUU",
    "IKKYUU",
    "SHODAN",
    "NIDAN",
    "SANDAN",
    "YONDAN",
    "GODAN",
    "ROKUDAN",
    "NANADAN",
    "HACHIDAN",
]

EXPECTED_DISPLAY_NAMES = {
    "MUKYUU": "Mukyū",
    "ROKKYUU": "Rokkyū (6-kyu)",
    "GOKYUU": "Gokyū (5-kyu)",
    "YONKYUU": "Yonkyū (4-kyu)",
    "SANKYUU": "Sankyū (3-kyu)",
    "NIKYUU": "Nikyū (2-kyu)",
    "IKKYUU": "Ikkyū (1-kyu)",
    "SHODAN": "Shodan (1-dan)",
    "NIDAN": "Nidan (2-dan)",
    "SANDAN": "Sandan (3-dan)",
    "YONDAN": "Yondan (4-dan)",
    "GODAN": "Godan (5-dan)",
    "ROKUDAN": "Rokudan (6-dan)",
    "NANADAN": "Nanadan (7-dan)",
    "HACHIDAN": "Hachidan (8-dan)",
}


def test_grade_enum_order() -> None:
    """Grade enum must define exactly 15 grades in the correct order."""
    grades = list(Grade)
    values = [g.value for g in grades]
    assert values == EXPECTED_GRADE_ORDER, (
        f"Grade order mismatch.\nExpected: {EXPECTED_GRADE_ORDER}\nGot:      {values}"
    )
    assert len(grades) == 15


def test_grade_display_names() -> None:
    """Every grade must expose a display_name with romanized name and kyu/dan helper."""
    for grade in Grade:
        expected = EXPECTED_DISPLAY_NAMES[grade.value]
        assert grade.display_name == expected, (
            f"{grade.value}: expected display_name={expected!r}, got {grade.display_name!r}"
        )
    # Spot-check the helper text in kyu grades
    assert "6-kyu" in Grade.ROKKYUU.display_name
    assert "5-kyu" in Grade.GOKYUU.display_name
    # Spot-check the helper text in dan grades
    assert "1-dan" in Grade.SHODAN.display_name
    assert "8-dan" in Grade.HACHIDAN.display_name


# ---------------------------------------------------------------------------
# AC2/AC3 — POST /members/{id}/promote
# ---------------------------------------------------------------------------


async def test_promote_from_mukyuu_to_rokkyuu(member_repo, grade_repo) -> None:
    """POST /promote is removed (issue #144) — must return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 404


async def test_promote_increments_grade(member_repo, grade_repo) -> None:
    """POST /promote is removed (issue #144) — must return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 404


async def test_promote_beyond_hachidan_fails(member_repo, grade_repo) -> None:
    """POST /promote is removed (issue #144) — must return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 404


async def test_promote_records_admin_and_date(member_repo, grade_repo) -> None:
    """POST /promote is removed (issue #144) — must return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC4 — GET /members/{id}/grades (history, chronological)
# ---------------------------------------------------------------------------


async def test_grade_history_chronological(member_repo, grade_repo) -> None:
    """GET /members/{id}/grades returns history with oldest entry first."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    member_id = _MEMBER_A_ID

    # Seed three promotions in order
    await grade_repo.add_promotion(
        member_id=member_id,
        grade="ROKKYUU",
        display_name="Rokkyū (6-kyu)",
        assigned_by=_ADMIN.sub,
        promoted_at="2024-01-01T10:00:00+00:00",
    )
    await grade_repo.add_promotion(
        member_id=member_id,
        grade="GOKYUU",
        display_name="Gokyū (5-kyu)",
        assigned_by=_ADMIN.sub,
        promoted_at="2024-06-01T10:00:00+00:00",
    )
    await grade_repo.add_promotion(
        member_id=member_id,
        grade="YONKYUU",
        display_name="Yonkyū (4-kyu)",
        assigned_by=_ADMIN.sub,
        promoted_at="2025-01-01T10:00:00+00:00",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{member_id}/grades")

    assert response.status_code == 200
    history = response.json()
    assert len(history) == 3
    assert history[0]["grade"] == "ROKKYUU"
    assert history[1]["grade"] == "GOKYUU"
    assert history[2]["grade"] == "YONKYUU"
    # Each entry must have required fields
    for entry in history:
        assert "id" in entry
        assert "member_id" in entry
        assert "grade" in entry
        assert "display_name" in entry
        assert "promoted_at" in entry
        assert "assigned_by" in entry, "History entries must include assigned_by"
        assert "awarded_by" not in entry, (
            "History entries must NOT include old field awarded_by"
        )
        assert "status" in entry, "History entries must include status"


# ---------------------------------------------------------------------------
# AC5/AC6 — Grade history access control
# ---------------------------------------------------------------------------


async def test_grade_history_own_member(member_repo, grade_repo) -> None:
    """A member can read their own grade history — 200."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    member_id = _MEMBER_A_ID

    await grade_repo.add_promotion(
        member_id=member_id,
        grade="ROKKYUU",
        display_name="Rokkyū (6-kyu)",
        assigned_by=_ADMIN.sub,
        promoted_at="2024-01-01T10:00:00+00:00",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{member_id}/grades")

    assert response.status_code == 200
    history = response.json()
    assert len(history) == 1
    assert history[0]["grade"] == "ROKKYUU"


async def test_grade_history_other_member_forbidden(member_repo, grade_repo) -> None:
    """A non-admin member cannot read another member's grade history — 403."""
    # Member B tries to read Member A's history
    app.dependency_overrides[REQUIRE_MEMBER] = _member_b_override
    member_a_id = _MEMBER_A_ID

    await grade_repo.add_promotion(
        member_id=member_a_id,
        grade="ROKKYUU",
        display_name="Rokkyū (6-kyu)",
        assigned_by=_ADMIN.sub,
        promoted_at="2024-01-01T10:00:00+00:00",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{member_a_id}/grades")

    assert response.status_code == 403


async def test_grade_history_admin_can_read_any(member_repo, grade_repo) -> None:
    """An admin can read any member's grade history — 200."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    member_id = _MEMBER_A_ID

    await grade_repo.add_promotion(
        member_id=member_id,
        grade="SHODAN",
        display_name="Shodan (1-dan)",
        assigned_by=_ADMIN.sub,
        promoted_at="2025-01-01T10:00:00+00:00",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{member_id}/grades")

    assert response.status_code == 200
    history = response.json()
    assert len(history) == 1
    assert history[0]["grade"] == "SHODAN"


# ===========================================================================
# Issue #144 — New grade endpoint tests
# ===========================================================================

# ---------------------------------------------------------------------------
# AC1 — POST /members/{id}/promote must be removed (404)
# ---------------------------------------------------------------------------


async def test_promote_endpoint_removed_returns_404(member_repo, grade_repo) -> None:
    """AC1: POST /members/{id}/promote must no longer exist — should return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 404, (
        f"POST /members/{{id}}/promote must be removed; got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# AC2 — POST /members/{id}/grades creates a confirmed history entry
# ---------------------------------------------------------------------------


async def test_post_grades_creates_confirmed_entry(member_repo, grade_repo) -> None:
    """AC2: POST /members/{id}/grades (admin only) creates a confirmed grade entry."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades",
            json={"grade": "SHODAN", "awarded_at": "2025-01-15T10:00:00+00:00"},
        )

    assert response.status_code == 201, (
        f"Expected 201 Created, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["grade"] == "SHODAN"
    assert body["status"] == "confirmed"
    assert body["member_id"] == member_id
    assert "id" in body


async def test_awarded_at_is_stored_in_utc(member_repo, grade_repo) -> None:
    """promoted_at is a timestamptz read back in UTC (#433); the write
    response says the same, not the offset the client happened to send."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/grades",
            json={"grade": "SHODAN", "awarded_at": "2025-01-15T10:00:00+09:00"},
        )

    assert response.status_code == 201, response.text
    assert response.json()["awarded_at"] == "2025-01-15T01:00:00+00:00"


async def test_awarded_at_without_an_offset_is_refused(member_repo, grade_repo) -> None:
    """A naive timestamp names no instant; the #433 migration refuses those
    too, so the API does not write new ones."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/grades",
            json={"grade": "SHODAN", "awarded_at": "2025-01-15T10:00:00"},
        )

    assert response.status_code == 422, response.text


async def test_post_grades_non_admin_forbidden(
    member_repo, grade_repo, cookies_for
) -> None:
    """AC2: POST /members/{id}/grades is admin-only — non-admin gets 401/403.

    No REQUIRE_ADMIN override is set, so the real guard fires against a real
    member token — overriding the guard here would test nothing.
    """
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api",
        cookies=cookies_for(_MEMBER_A),
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades",
            json={"grade": "SHODAN"},
        )

    assert response.status_code in (
        401,
        403,
    ), f"Non-admin must be rejected; got {response.status_code}"


async def test_post_grades_member_not_found(member_repo, grade_repo) -> None:
    """AC2: POST /members/{id}/grades returns 404 when member does not exist."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    nonexistent_id = "00000000-0000-0000-0000-000000000099"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{nonexistent_id}/grades",
            json={"grade": "SHODAN"},
        )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC3 — awarded_at defaults to server-side UTC now when omitted
# ---------------------------------------------------------------------------


async def test_post_grades_awarded_at_defaults_to_now(member_repo, grade_repo) -> None:
    """AC3: Omitting awarded_at results in a server-generated UTC timestamp."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    before = datetime.now(UTC)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades",
            json={"grade": "ROKKYUU"},
            # No awarded_at field
        )

    after = datetime.now(UTC)

    assert response.status_code == 201, (
        f"Expected 201 Created, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "awarded_at" in body or "promoted_at" in body, (
        "Response must include an awarded_at (or promoted_at) timestamp"
    )
    ts_raw = body.get("awarded_at") or body.get("promoted_at")
    ts = datetime.fromisoformat(ts_raw)
    # Normalise to UTC for comparison
    if ts.tzinfo is None:
        import datetime as _dt

        ts = ts.replace(tzinfo=_dt.UTC)
    assert before <= ts <= after, (
        f"Server timestamp {ts} must be between {before} and {after}"
    )


# ---------------------------------------------------------------------------
# AC4 — Invalid grade value → 422; MUKYUU → 422
# ---------------------------------------------------------------------------


async def test_post_grades_invalid_grade_value_returns_422(
    member_repo, grade_repo
) -> None:
    """AC4: Posting an unrecognised grade value returns 422."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades",
            json={"grade": "NOTAGRADE"},
        )

    assert response.status_code == 422, (
        f"Invalid grade must return 422, got {response.status_code}"
    )


async def test_post_grades_mukyuu_returns_422(member_repo, grade_repo) -> None:
    """AC4: MUKYUU is the default/ungraded state and cannot be explicitly assigned — 422."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades",
            json={"grade": "MUKYUU"},
        )

    assert response.status_code == 422, (
        f"MUKYUU must not be assignable via POST /grades; got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# AC5 — GET /members/{id}/grades omits assigned_by for non-admin callers
# ---------------------------------------------------------------------------


async def test_get_grades_omits_assigned_by_for_non_admin(
    member_repo, grade_repo
) -> None:
    """AC5: Non-admin callers must NOT see assigned_by in grade history entries."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    member_id = _MEMBER_A_ID

    await grade_repo.add_promotion(
        member_id=member_id,
        grade="ROKKYUU",
        display_name="Rokkyū (6-kyu)",
        assigned_by=_ADMIN.sub,
        promoted_at="2024-01-01T10:00:00+00:00",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{member_id}/grades")

    assert response.status_code == 200
    history = response.json()
    assert len(history) == 1
    entry = history[0]
    assert "assigned_by" not in entry, (
        "Non-admin callers must not see assigned_by in grade history"
    )


async def test_get_grades_includes_assigned_by_for_admin(
    member_repo, grade_repo
) -> None:
    """AC5: Admin callers MUST see assigned_by in grade history entries."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    member_id = _MEMBER_A_ID

    await grade_repo.add_promotion(
        member_id=member_id,
        grade="SHODAN",
        display_name="Shodan (1-dan)",
        assigned_by=_ADMIN.sub,
        promoted_at="2025-01-01T10:00:00+00:00",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{member_id}/grades")

    assert response.status_code == 200
    history = response.json()
    assert len(history) == 1
    entry = history[0]
    assert "assigned_by" in entry, "Admin callers must see assigned_by"
    assert entry["assigned_by"] == _ADMIN.sub


# ---------------------------------------------------------------------------
# AC6 — Current grade derived as latest confirmed entry by awarded_at
# ---------------------------------------------------------------------------


async def test_current_grade_is_latest_confirmed_by_awarded_at(
    member_repo, grade_repo
) -> None:
    """AC6: Current grade is the most recent confirmed entry ordered by awarded_at."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    member_id = _MEMBER_A_ID

    # Seed entries out of insertion order — latest awarded_at is SANDAN
    await grade_repo.add_promotion(
        member_id=member_id,
        grade="GOKYUU",
        display_name="Gokyū (5-kyu)",
        assigned_by=_ADMIN.sub,
        promoted_at="2023-01-01T10:00:00+00:00",
        status="confirmed",
    )
    await grade_repo.add_promotion(
        member_id=member_id,
        grade="SANDAN",
        display_name="Sandan (3-dan)",
        assigned_by=_ADMIN.sub,
        promoted_at="2025-06-01T10:00:00+00:00",
        status="confirmed",
    )
    await grade_repo.add_promotion(
        member_id=member_id,
        grade="SHODAN",
        display_name="Shodan (1-dan)",
        assigned_by=_ADMIN.sub,
        promoted_at="2024-01-01T10:00:00+00:00",
        status="confirmed",
    )

    # GET the member's detail or a dedicated current-grade endpoint
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{member_id}/grades/current")

    assert response.status_code == 200, (
        f"GET /members/{{id}}/grades/current must exist; got {response.status_code}"
    )
    body = response.json()
    assert body["grade"] == "SANDAN", (
        f"Current grade must be the latest confirmed entry by awarded_at; got {body.get('grade')}"
    )


async def test_current_grade_ignores_non_confirmed_entries(
    member_repo, grade_repo
) -> None:
    """AC6: Only confirmed entries contribute to current grade determination."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    member_id = _MEMBER_A_ID

    # A confirmed SHODAN followed by a pending NIDAN — current must still be SHODAN
    await grade_repo.add_promotion(
        member_id=member_id,
        grade="SHODAN",
        display_name="Shodan (1-dan)",
        assigned_by=_ADMIN.sub,
        promoted_at="2024-01-01T10:00:00+00:00",
        status="confirmed",
    )
    await grade_repo.add_promotion(
        member_id=member_id,
        grade="NIDAN",
        display_name="Nidan (2-dan)",
        assigned_by=_ADMIN.sub,
        promoted_at="2025-01-01T10:00:00+00:00",
        status="pending",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{member_id}/grades/current")

    assert response.status_code == 200
    body = response.json()
    assert body["grade"] == "SHODAN", (
        f"Non-confirmed entries must not affect current grade; got {body.get('grade')}"
    )


# ---------------------------------------------------------------------------
# AC11 — Rokkyu promotion bug is no longer reproducible
# ---------------------------------------------------------------------------


async def test_rokkyu_bug_cannot_skip_grade_via_post_grades(
    member_repo, grade_repo
) -> None:
    """AC11: The old promote endpoint bug that skipped MUKYUU to ROKKYUU is gone.

    The new POST /grades endpoint must assign exactly the grade specified,
    with no automatic progression. ROKKYUU can be assigned explicitly to a
    member with no prior grade (previously required going through promote).
    """
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    # Explicitly assign ROKKYUU to a member with no prior grade history
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades",
            json={"grade": "ROKKYUU"},
        )

    assert response.status_code == 201, (
        f"Should be able to assign ROKKYUU directly; got {response.status_code}"
    )
    body = response.json()
    assert body["grade"] == "ROKKYUU"
    # No phantom MUKYUU entry should have been created
    history = await grade_repo.get_history(member_id)
    assert len(history) == 1, (
        f"Only one entry should exist — no phantom MUKYUU; found {len(history)}"
    )
    assert history[0]["grade"] == "ROKKYUU"


async def test_rokkyu_bug_promote_endpoint_gone(member_repo, grade_repo) -> None:
    """AC11: The old /promote endpoint that caused the Rokkyu bug is gone."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    # The bug-causing endpoint must be removed
    assert response.status_code == 404, (
        f"POST /promote must be gone (404); got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Issue #145 — Grade proposal (member self-report)
# ---------------------------------------------------------------------------


async def test_propose_creates_pending_entry(member_repo, grade_repo) -> None:
    """MEMBER_A proposes SHODAN for their own record → 201, status==pending, assigned_by is None."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades/propose",
            json={"grade": "SHODAN"},
        )

    assert response.status_code == 201, (
        f"Expected 201 Created, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["grade"] == "SHODAN"
    assert body["status"] == "pending"
    assert body.get("assigned_by") is None, (
        "Self-proposed grade must have assigned_by=None"
    )
    assert body["member_id"] == member_id


async def test_propose_own_record_member_cannot_propose_for_other(
    member_repo, grade_repo
) -> None:
    """MEMBER_A tries to propose for MEMBER_B_ID → 403."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    other_member_id = _MEMBER_B_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{other_member_id}/grades/propose",
            json={"grade": "SHODAN"},
        )

    assert response.status_code == 403, (
        f"Member must not be able to propose for another member; got {response.status_code}"
    )


async def test_propose_admin_forbidden(member_repo, grade_repo) -> None:
    """Admin tries POST /propose → 403 (admin cannot use member-only endpoint)."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades/propose",
            json={"grade": "SHODAN"},
        )

    assert response.status_code == 403, (
        f"Admin must not be able to use the member-only propose endpoint; got {response.status_code}"
    )


async def test_propose_pending_entry_visible_to_own_member(
    member_repo, grade_repo
) -> None:
    """MEMBER_A proposes grade, then GET /grades as MEMBER_A → pending entry included."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        propose_response = await c.post(
            f"/members/{member_id}/grades/propose",
            json={"grade": "SHODAN"},
        )
        assert propose_response.status_code == 201, (
            f"Propose step failed: {propose_response.status_code}: {propose_response.text}"
        )

        history_response = await c.get(f"/members/{member_id}/grades")

    assert history_response.status_code == 200
    history = history_response.json()
    pending_entries = [e for e in history if e.get("status") == "pending"]
    assert len(pending_entries) >= 1, (
        "Pending entry must be visible to the proposing member in their own grade history"
    )
    assert pending_entries[0]["grade"] == "SHODAN"


async def test_propose_pending_entry_not_visible_to_other_member(
    member_repo, grade_repo
) -> None:
    """MEMBER_A's pending entry NOT visible when MEMBER_B tries to view MEMBER_A's grades — 403.

    Uses the propose endpoint to create the pending entry (so the test fails until
    the endpoint exists), then confirms MEMBER_B cannot see MEMBER_A's history.
    """
    # MEMBER_A proposes a grade via the new endpoint
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        propose_response = await c.post(
            f"/members/{_MEMBER_A_ID}/grades/propose",
            json={"grade": "SHODAN"},
        )
    assert propose_response.status_code == 201, (
        f"Propose step must succeed; got {propose_response.status_code}: {propose_response.text}"
    )

    # MEMBER_B tries to read MEMBER_A's grade history — must be 403
    app.dependency_overrides[REQUIRE_MEMBER] = _member_b_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{_MEMBER_A_ID}/grades")

    assert response.status_code == 403, (
        f"Member B must not be able to read Member A's grades; got {response.status_code}"
    )


async def test_propose_mukyuu_returns_422(member_repo, grade_repo) -> None:
    """Proposing MUKYUU → 422."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades/propose",
            json={"grade": "MUKYUU"},
        )

    assert response.status_code == 422, (
        f"MUKYUU must not be proposable; got {response.status_code}"
    )


async def test_propose_invalid_grade_returns_422(member_repo, grade_repo) -> None:
    """Proposing 'NOTAGRADE' → 422."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades/propose",
            json={"grade": "NOTAGRADE"},
        )

    assert response.status_code == 422, (
        f"Invalid grade must return 422; got {response.status_code}"
    )
