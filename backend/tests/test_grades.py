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
    """Promoting a Mukyū member advances them to Rokkyū."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 200
    body = response.json()
    # The new grade should be Rokkyū
    assert body["grade"] == "ROKKYUU"
    assert body["display_name"] == "Rokkyū (6-kyu)"
    assert body["member_id"] == _MEMBER_A_ID


@pytest.mark.anyio
async def test_promote_increments_grade(member_repo, grade_repo) -> None:
    """Promoting twice from Mukyū results in Gokyū."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(f"/members/{member_id}/promote")  # → Rokkyū
        response = await c.post(f"/members/{member_id}/promote")  # → Gokyū

    assert response.status_code == 200
    body = response.json()
    assert body["grade"] == "GOKYUU"
    assert body["display_name"] == "Gokyū (5-kyu)"


@pytest.mark.anyio
async def test_promote_beyond_hachidan_fails(member_repo, grade_repo) -> None:
    """Promoting a member already at Hachidan must return 400."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    # Seed the grade repo so the member is already at Hachidan
    await grade_repo.add_promotion(
        member_id=member_id,
        grade="HACHIDAN",
        display_name="Hachidan (8-dan)",
        assigned_by=_ADMIN.sub,
        promoted_at=datetime.now(UTC).isoformat(),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 400
    assert "hachidan" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_promote_records_admin_and_date(member_repo, grade_repo) -> None:
    """Promotion response includes assigned_by (admin member_id), promoted_at, and status."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/promote")

    assert response.status_code == 200
    body = response.json()
    assert "assigned_by" in body, "Response must include assigned_by"
    assert "awarded_by" not in body, "Response must NOT include old field awarded_by"
    assert "promoted_at" in body, "Response must include promoted_at"
    assert "status" in body, "Response must include status"
    assert body["assigned_by"] == _ADMIN.sub
    assert body["status"] == "confirmed"
    # promoted_at must be a parseable ISO timestamp
    promoted_at = datetime.fromisoformat(body["promoted_at"])
    assert promoted_at is not None


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
