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

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.grades.dependencies import get_grade_repo  # noqa: F401 — will fail (red)
from app.grades.models import Grade  # noqa: F401 — will fail (red)
from app.main import app
from app.members.dependencies import get_member_repo  # noqa: F401 — will fail (red)

# ---------------------------------------------------------------------------
# Auth claim helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER_A = UserClaims(
    sub="member-a-uuid", email="member-a@dojo.test", role="member", is_active=True
)
_MEMBER_B = UserClaims(
    sub="member-b-uuid", email="member-b@dojo.test", role="member", is_active=True
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
# Stub repositories
# ---------------------------------------------------------------------------

_MEMBER_A_RECORD: dict[str, Any] = {
    "id": _MEMBER_A_ID,
    "email": "member-a@dojo.test",
    "full_name": "Member A",
    "user_id": _MEMBER_A.sub,
    "membership_status": "active",
}

_MEMBER_B_RECORD: dict[str, Any] = {
    "id": _MEMBER_B_ID,
    "email": "member-b@dojo.test",
    "full_name": "Member B",
    "user_id": _MEMBER_B.sub,
    "membership_status": "active",
}


class StubMemberRepo:
    """Minimal in-memory member repository for grade tests."""

    def __init__(self, members: list[dict[str, Any]] | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        for m in members or [_MEMBER_A_RECORD, _MEMBER_B_RECORD]:
            self._store[m["id"]] = dict(m)

    async def get(self, member_id: str) -> dict[str, Any] | None:
        return self._store.get(member_id)

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        for item in self._store.values():
            if item["email"] == email:
                return item
        return None

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
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
        self, status: str | None = None, search: str | None = None
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


class StubGradeRepo:
    """In-memory grade history repository.

    Each entry shape:
      { id, member_id, grade (machine value), display_name, promoted_at (ISO), assigned_by, status }
    """

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    async def get_current_grade(self, member_id: str) -> str | None:
        """Return the machine value of the member's current grade, or None."""
        member_entries = [e for e in self._history if e["member_id"] == member_id]
        if not member_entries:
            return None
        return member_entries[-1]["grade"]

    async def add_promotion(
        self,
        member_id: str,
        grade: str,
        display_name: str,
        assigned_by: str,
        promoted_at: str,
        status: str = "confirmed",
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "member_id": member_id,
            "grade": grade,
            "display_name": display_name,
            "assigned_by": assigned_by,
            "promoted_at": promoted_at,
            "status": status,
        }
        self._history.append(entry)
        return entry

    async def get_history(self, member_id: str) -> list[dict[str, Any]]:
        """Return history for member in chronological order (oldest first)."""
        return [e for e in self._history if e["member_id"] == member_id]


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


@pytest.fixture()
def grade_repo() -> StubGradeRepo:
    repo = StubGradeRepo()
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
    assert (
        values == EXPECTED_GRADE_ORDER
    ), f"Grade order mismatch.\nExpected: {EXPECTED_GRADE_ORDER}\nGot:      {values}"
    assert len(grades) == 15


def test_grade_display_names() -> None:
    """Every grade must expose a display_name with romanized name and kyu/dan helper."""
    for grade in Grade:
        expected = EXPECTED_DISPLAY_NAMES[grade.value]
        assert (
            grade.display_name == expected
        ), f"{grade.value}: expected display_name={expected!r}, got {grade.display_name!r}"
    # Spot-check the helper text in kyu grades
    assert "6-kyu" in Grade.ROKKYUU.display_name
    assert "5-kyu" in Grade.GOKYUU.display_name
    # Spot-check the helper text in dan grades
    assert "1-dan" in Grade.SHODAN.display_name
    assert "8-dan" in Grade.HACHIDAN.display_name


# ---------------------------------------------------------------------------
# AC2/AC3 — POST /members/{id}/promote
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_promote_from_mukyuu_to_rokkyuu(member_repo, grade_repo) -> None:
    """POST /promote is removed (issue #144) — must return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_promote_increments_grade(member_repo, grade_repo) -> None:
    """POST /promote is removed (issue #144) — must return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_promote_beyond_hachidan_fails(member_repo, grade_repo) -> None:
    """POST /promote is removed (issue #144) — must return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_promote_records_admin_and_date(member_repo, grade_repo) -> None:
    """POST /promote is removed (issue #144) — must return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC4 — GET /members/{id}/grades (history, chronological)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
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
        transport=ASGITransport(app=app), base_url="http://test"
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
        assert (
            "awarded_by" not in entry
        ), "History entries must NOT include old field awarded_by"
        assert "status" in entry, "History entries must include status"


# ---------------------------------------------------------------------------
# AC5/AC6 — Grade history access control
# ---------------------------------------------------------------------------


@pytest.mark.anyio
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
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{member_id}/grades")

    assert response.status_code == 200
    history = response.json()
    assert len(history) == 1
    assert history[0]["grade"] == "ROKKYUU"


@pytest.mark.anyio
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
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{member_a_id}/grades")

    assert response.status_code == 403


@pytest.mark.anyio
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
        transport=ASGITransport(app=app), base_url="http://test"
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


@pytest.mark.anyio
async def test_promote_endpoint_removed_returns_404(member_repo, grade_repo) -> None:
    """AC1: POST /members/{id}/promote must no longer exist — should return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 404, (
        f"POST /members/{{id}}/promote must be removed; got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# AC2 — POST /members/{id}/grades creates a confirmed history entry
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_post_grades_creates_confirmed_entry(member_repo, grade_repo) -> None:
    """AC2: POST /members/{id}/grades (admin only) creates a confirmed grade entry."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
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


@pytest.mark.anyio
async def test_post_grades_non_admin_forbidden(member_repo, grade_repo) -> None:
    """AC2: POST /members/{id}/grades is admin-only — non-admin gets 401/403."""
    app.dependency_overrides[REQUIRE_ADMIN] = _member_a_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades",
            json={"grade": "SHODAN"},
        )

    assert response.status_code in (401, 403), (
        f"Non-admin must be rejected; got {response.status_code}"
    )


@pytest.mark.anyio
async def test_post_grades_member_not_found(member_repo, grade_repo) -> None:
    """AC2: POST /members/{id}/grades returns 404 when member does not exist."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    nonexistent_id = "00000000-0000-0000-0000-000000000099"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/members/{nonexistent_id}/grades",
            json={"grade": "SHODAN"},
        )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC3 — awarded_at defaults to server-side UTC now when omitted
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_post_grades_awarded_at_defaults_to_now(member_repo, grade_repo) -> None:
    """AC3: Omitting awarded_at results in a server-generated UTC timestamp."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    before = datetime.now(UTC)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
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


@pytest.mark.anyio
async def test_post_grades_invalid_grade_value_returns_422(
    member_repo, grade_repo
) -> None:
    """AC4: Posting an unrecognised grade value returns 422."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/grades",
            json={"grade": "NOTAGRADE"},
        )

    assert response.status_code == 422, (
        f"Invalid grade must return 422, got {response.status_code}"
    )


@pytest.mark.anyio
async def test_post_grades_mukyuu_returns_422(member_repo, grade_repo) -> None:
    """AC4: MUKYUU is the default/ungraded state and cannot be explicitly assigned — 422."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
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


@pytest.mark.anyio
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
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{member_id}/grades")

    assert response.status_code == 200
    history = response.json()
    assert len(history) == 1
    entry = history[0]
    assert "assigned_by" not in entry, (
        "Non-admin callers must not see assigned_by in grade history"
    )


@pytest.mark.anyio
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
        transport=ASGITransport(app=app), base_url="http://test"
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


@pytest.mark.anyio
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
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{member_id}/grades/current")

    assert response.status_code == 200, (
        f"GET /members/{{id}}/grades/current must exist; got {response.status_code}"
    )
    body = response.json()
    assert body["grade"] == "SANDAN", (
        f"Current grade must be the latest confirmed entry by awarded_at; got {body.get('grade')}"
    )


@pytest.mark.anyio
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
        transport=ASGITransport(app=app), base_url="http://test"
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


@pytest.mark.anyio
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
        transport=ASGITransport(app=app), base_url="http://test"
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
    history = grade_repo._history
    assert len(history) == 1, (
        f"Only one entry should exist — no phantom MUKYUU; found {len(history)}"
    )
    assert history[0]["grade"] == "ROKKYUU"


@pytest.mark.anyio
async def test_rokkyu_bug_promote_endpoint_gone(member_repo, grade_repo) -> None:
    """AC11: The old /promote endpoint that caused the Rokkyu bug is gone."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    # The bug-causing endpoint must be removed
    assert response.status_code == 404, (
        f"POST /promote must be gone (404); got {response.status_code}"
    )
