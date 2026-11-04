"""
Unit / integration tests for issue #11 — Reports and CSV export.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. GET /reports/attendance returns sessions in date range with headcount and member rates
  2. GET /reports/members returns all members with current grade and join date
  3. GET /reports/attendance/csv and GET /reports/members/csv return valid CSV files
  5. Reports are accessible to admins only (401/403 guards)
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.main import app
from tests.auth_support import sign_in

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER = AccountClaims(sub="member-uuid", email="member@dojo.test", role="member")


def _admin_override():
    return _ADMIN


def _member_token() -> str:
    return sign_in(_MEMBER)


# ---------------------------------------------------------------------------
# Stub repositories
# ---------------------------------------------------------------------------


class StubReportRepository:
    """In-memory stand-in for a report repository.

    Stores session instances (with date) and attendance records so the router
    can compute headcounts and per-member attendance rates.
    """

    def __init__(self) -> None:
        # List of session dicts: {id, date, cancelled}
        self._sessions: list[dict[str, Any]] = []
        # List of attendance dicts: {id, session_id, member_id, visitor_name, ...}
        self._attendance: list[dict[str, Any]] = []
        # List of member dicts: {id, display_name, email, join_date, ...}
        self._members: list[dict[str, Any]] = []
        # List of grade history dicts: {id, member_id, grade, promoted_at, ...}
        self._grades: list[dict[str, Any]] = []

    def seed_session(self, date: str, cancelled: bool = False) -> dict[str, Any]:
        record = {"id": str(uuid.uuid4()), "date": date, "cancelled": cancelled}
        self._sessions.append(record)
        return record

    def seed_attendance(self, session_id: str, member_id: str | None) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "member_id": member_id,
            "visitor_name": None if member_id else "Visitor",
        }
        self._attendance.append(record)
        return record

    def seed_member(
        self,
        display_name: str = "Test Member",
        join_date: str = "2024-01-01",
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "display_name": display_name,
            "email": f"{display_name.lower().replace(' ', '.')}@test.com",
            "join_date": join_date,
            "membership_status": "active",
        }
        self._members.append(record)
        return record

    def seed_grade(
        self, member_id: str, grade: str, promoted_at: str, status: str = "confirmed"
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "member_id": member_id,
            "grade": grade,
            "promoted_at": promoted_at,
            "status": status,
        }
        self._grades.append(record)
        return record

    def _held(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        return [
            s
            for s in self._sessions
            if date_from <= s["date"] <= date_to and not s["cancelled"]
        ]

    # --- Report query methods (will be called by the router) ---

    async def attendance_report(
        self, date_from: str, date_to: str
    ) -> list[dict[str, Any]]:
        """Return held Sessions in range with headcount."""
        result = []
        for session in self._held(date_from, date_to):
            attendance = [
                a for a in self._attendance if a["session_id"] == session["id"]
            ]
            result.append(
                {
                    "session_id": session["id"],
                    "date": session["date"],
                    "headcount": len(attendance),
                }
            )
        return result

    async def member_attendance_rates(
        self, date_from: str, date_to: str
    ) -> list[dict[str, Any]]:
        """Attendance Rate (GLOSSARY.md), as SqlReportRepository serves it:
        Members who attended, plus active Members who did not, each counted
        over held Sessions from the later of date_from and their join date.
        """
        result = []
        for member in self._members:
            held = {
                s["id"]
                for s in self._held(max(date_from, member["join_date"]), date_to)
            }
            count = sum(
                1
                for a in self._attendance
                if a["member_id"] == member["id"] and a["session_id"] in held
            )
            if not held or (count == 0 and member["membership_status"] != "active"):
                continue
            result.append(
                {
                    "member_id": member["id"],
                    "display_name": member["display_name"],
                    "sessions_attended": count,
                    "total_sessions": len(held),
                    "attendance_rate": round(count / len(held), 4),
                }
            )
        return result

    async def members_report(self) -> list[dict[str, Any]]:
        """Return all members with current grade and join date."""
        result = []
        for member in self._members:
            confirmed = [
                g
                for g in self._grades
                if g["member_id"] == member["id"] and g["status"] == "confirmed"
            ]
            current = max(confirmed, key=lambda g: g["promoted_at"], default=None)
            current_grade = current["grade"] if current else None
            result.append(
                {
                    "member_id": member["id"],
                    "display_name": member["display_name"],
                    "join_date": member["join_date"],
                    "current_grade": current_grade,
                }
            )
        return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def report_repo() -> StubReportRepository:
    from app.reports.dependencies import get_report_repo  # noqa: PLC0415

    repo = StubReportRepository()
    app.dependency_overrides[get_report_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — GET /reports/attendance (date range, headcount, member rates)
# ---------------------------------------------------------------------------


async def test_attendance_report_returns_sessions_in_range(
    report_repo: StubReportRepository,
) -> None:
    """Sessions within the date range appear in the report."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    s1 = report_repo.seed_session("2025-01-10")
    s2 = report_repo.seed_session("2025-01-17")
    # Seed some attendance for headcount
    report_repo.seed_attendance(s1["id"], "member-1")
    report_repo.seed_attendance(s1["id"], "member-2")
    report_repo.seed_attendance(s2["id"], "member-1")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/reports/attendance",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )

    assert response.status_code == 200
    body = response.json()
    assert "sessions" in body
    sessions = body["sessions"]
    assert len(sessions) == 2
    session_ids = {s["session_id"] for s in sessions}
    assert s1["id"] in session_ids
    assert s2["id"] in session_ids


async def test_attendance_report_excludes_sessions_outside_range(
    report_repo: StubReportRepository,
) -> None:
    """Sessions outside the date range, and cancelled ones, are excluded."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    report_repo.seed_session("2024-12-31")  # before range
    in_range = report_repo.seed_session("2025-01-15")
    report_repo.seed_session("2025-01-22", cancelled=True)
    report_repo.seed_session("2025-02-01")  # after range

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/reports/attendance",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )

    assert response.status_code == 200
    body = response.json()
    sessions = body["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == in_range["id"]


async def test_attendance_report_includes_headcount(
    report_repo: StubReportRepository,
) -> None:
    """Each session entry has a headcount equal to attendance record count."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    session = report_repo.seed_session("2025-01-10")
    report_repo.seed_attendance(session["id"], "member-1")
    report_repo.seed_attendance(session["id"], "member-2")
    report_repo.seed_attendance(session["id"], "member-3")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/reports/attendance",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )

    assert response.status_code == 200
    body = response.json()
    session_entry = next(
        s for s in body["sessions"] if s["session_id"] == session["id"]
    )
    assert session_entry["headcount"] == 3


async def test_attendance_report_includes_member_rates(
    report_repo: StubReportRepository,
) -> None:
    """Response includes per-member attendance rates for the date range."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    m1 = report_repo.seed_member("Alice Kendo")
    m2 = report_repo.seed_member("Bob Kendo")
    m3 = report_repo.seed_member("Chie Kendo")
    s1 = report_repo.seed_session("2025-01-10")
    s2 = report_repo.seed_session("2025-01-17")
    report_repo.seed_session("2025-01-24", cancelled=True)
    # member-1 attended both; member-2 attended only s1; member-3 neither
    report_repo.seed_attendance(s1["id"], m1["id"])
    report_repo.seed_attendance(s2["id"], m1["id"])
    report_repo.seed_attendance(s1["id"], m2["id"])
    report_repo.seed_attendance(s1["id"], None)  # a Visitor

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/reports/attendance",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )

    assert response.status_code == 200
    body = response.json()
    assert "member_rates" in body
    rates = {
        r["member_id"]: (
            r["display_name"],
            r["sessions_attended"],
            r["total_sessions"],
            r["attendance_rate"],
        )
        for r in body["member_rates"]
    }
    assert rates == {
        m1["id"]: ("Alice Kendo", 2, 2, 1.0),
        m2["id"]: ("Bob Kendo", 1, 2, 0.5),
        m3["id"]: ("Chie Kendo", 0, 2, 0.0),
    }


async def test_attendance_report_missing_date_params_returns_422(
    report_repo: StubReportRepository,
) -> None:
    """date_from and date_to are required query params."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/reports/attendance")

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC2 — GET /reports/members
# ---------------------------------------------------------------------------


async def test_members_report_returns_all_members(
    report_repo: StubReportRepository,
) -> None:
    """Members report lists all members with join_date."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    m1 = report_repo.seed_member("Alice Kendo", "2023-04-01")
    m2 = report_repo.seed_member("Bob Kendo", "2024-09-01")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/reports/members")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2
    member_ids = {m["member_id"] for m in body}
    assert m1["id"] in member_ids
    assert m2["id"] in member_ids
    for entry in body:
        assert "display_name" in entry
        assert "join_date" in entry
        assert "current_grade" in entry


async def test_members_report_current_grade_none_when_no_history(
    report_repo: StubReportRepository,
) -> None:
    """current_grade is None for a member with no grade history."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    m = report_repo.seed_member("New Member", "2025-01-01")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/reports/members")

    assert response.status_code == 200
    body = response.json()
    entry = next(e for e in body if e["member_id"] == m["id"])
    assert entry["current_grade"] is None


async def test_members_report_shows_current_grade(
    report_repo: StubReportRepository,
) -> None:
    """current_grade is the most recent *confirmed* Promotion (#565)."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    m = report_repo.seed_member("Graded Member", "2022-06-01")
    report_repo.seed_grade(m["id"], "ROKKYUU", "2023-01-01T10:00:00")
    report_repo.seed_grade(m["id"], "GOKYUU", "2024-01-01T10:00:00")
    report_repo.seed_grade(m["id"], "YONKYUU", "2025-01-01T10:00:00", "pending")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/reports/members")

    assert response.status_code == 200
    body = response.json()
    entry = next(e for e in body if e["member_id"] == m["id"])
    assert entry["current_grade"] == "GOKYUU"


# ---------------------------------------------------------------------------
# AC3 — CSV endpoints
# ---------------------------------------------------------------------------


async def test_attendance_csv_content_type(
    report_repo: StubReportRepository,
) -> None:
    """GET /reports/attendance/csv returns text/csv content type."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    report_repo.seed_session("2025-01-10")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/reports/attendance/csv",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]


async def test_attendance_csv_has_correct_columns(
    report_repo: StubReportRepository,
) -> None:
    """Attendance CSV has session_id, date, and headcount columns."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    session = report_repo.seed_session("2025-01-10")
    report_repo.seed_attendance(session["id"], "member-1")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/reports/attendance/csv",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )

    assert response.status_code == 200
    lines = response.text.strip().splitlines()
    assert len(lines) >= 2  # header + at least one data row
    header = lines[0].lower()
    assert "session_id" in header
    assert "date" in header
    assert "headcount" in header


async def test_members_csv_content_type(
    report_repo: StubReportRepository,
) -> None:
    """GET /reports/members/csv returns text/csv content type."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    report_repo.seed_member("Alice", "2024-01-01")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/reports/members/csv")

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]


async def test_members_csv_has_correct_columns(
    report_repo: StubReportRepository,
) -> None:
    """Members CSV has member_id, display_name, join_date, and current_grade columns."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    m = report_repo.seed_member("Alice Kendo", "2024-01-01")
    report_repo.seed_grade(m["id"], "SHODAN", "2025-01-01T10:00:00")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/reports/members/csv")

    assert response.status_code == 200
    lines = response.text.strip().splitlines()
    assert len(lines) >= 2
    header = lines[0].lower()
    assert "member_id" in header
    assert "display_name" in header
    assert "join_date" in header
    assert "current_grade" in header


# ---------------------------------------------------------------------------
# AC5 — Admin-only access
# ---------------------------------------------------------------------------


async def test_attendance_report_unauthenticated_returns_401(
    report_repo: StubReportRepository,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/reports/attendance",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )

    assert response.status_code == 401


async def test_attendance_report_member_returns_403(
    report_repo: StubReportRepository,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/reports/attendance",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


async def test_members_report_unauthenticated_returns_401(
    report_repo: StubReportRepository,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/reports/members")

    assert response.status_code == 401


async def test_members_report_member_returns_403(
    report_repo: StubReportRepository,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/reports/members",
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


async def test_attendance_csv_unauthenticated_returns_401(
    report_repo: StubReportRepository,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/reports/attendance/csv",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )

    assert response.status_code == 401


async def test_members_csv_unauthenticated_returns_401(
    report_repo: StubReportRepository,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/reports/members/csv")

    assert response.status_code == 401
