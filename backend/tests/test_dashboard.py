"""
Unit/integration tests for issue #12 / #17 — Admin Dashboard endpoint.

Uses StubRepository pattern — NO real DB.

Acceptance criteria covered here:
  6.  GET /dashboard/admin returns { active_members, sessions_this_week,
      attendance_rate, attendance_trend } — admin only
  7.  GET /dashboard/admin with member token → 403
  8.  GET /dashboard/admin returns correct active member count from DB
  9.  attendance_trend > 0.0 when current 30-day rate > previous 30-day rate
  10. attendance_trend < 0.0 when current 30-day rate < previous 30-day rate
  11. attendance_trend is a float
  12. attendance_trend == 0.0 when both periods have no sessions
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import UserClaims
from app.auth.token import encode_token
from app.main import app

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = UserClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)


def _admin_override():
    return _ADMIN


def _member_token() -> str:
    return encode_token(_MEMBER)


# ---------------------------------------------------------------------------
# Stub repository
# ---------------------------------------------------------------------------

TODAY = date.today()


class StubDashboardRepo:
    """In-memory stand-in for the dashboard statistics repository."""

    def __init__(self) -> None:
        # Members: {id, membership_status}
        self._members: list[dict[str, Any]] = []
        # Sessions: {id, date (ISO string)}
        self._sessions: list[dict[str, Any]] = []
        # Attendance: {id, session_id, member_id}
        self._attendance: list[dict[str, Any]] = []

    # --- seed helpers ---

    def seed_member(self, status: str = "active") -> dict[str, Any]:
        record = {"id": str(uuid.uuid4()), "membership_status": status}
        self._members.append(record)
        return record

    def seed_session(self, session_date: date) -> dict[str, Any]:
        record = {"id": str(uuid.uuid4()), "date": session_date.isoformat()}
        self._sessions.append(record)
        return record

    def seed_attendance(self, session_id: str, member_id: str) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "member_id": member_id,
        }
        self._attendance.append(record)
        return record

    # --- query methods (called by the router) ---

    async def active_member_count(self) -> int:
        return sum(1 for m in self._members if m["membership_status"] == "active")

    async def sessions_this_week(self) -> int:
        start = TODAY - timedelta(days=TODAY.weekday())  # Monday
        end = start + timedelta(days=6)  # Sunday
        return sum(
            1
            for s in self._sessions
            if start.isoformat() <= s["date"] <= end.isoformat()
        )

    async def attendance_rate_for_period(self, date_from: date, date_to: date) -> float:
        sessions_in_range = [
            s
            for s in self._sessions
            if date_from.isoformat() <= s["date"] <= date_to.isoformat()
        ]
        if not sessions_in_range:
            return 0.0
        session_ids = {s["id"] for s in sessions_in_range}
        attended = sum(1 for a in self._attendance if a["session_id"] in session_ids)
        active_count = await self.active_member_count()
        if active_count == 0:
            return 0.0
        total_possible = len(sessions_in_range) * active_count
        return round(attended / total_possible, 4)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def dashboard_repo() -> StubDashboardRepo:
    from app.dashboard.dependencies import get_dashboard_repo  # noqa: PLC0415

    repo = StubDashboardRepo()
    app.dependency_overrides[get_dashboard_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC6 — GET /dashboard/admin returns the expected shape
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_dashboard_returns_expected_shape(
    dashboard_repo: StubDashboardRepo,
) -> None:
    """GET /dashboard/admin returns the four required stat keys."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/dashboard/admin")

    assert response.status_code == 200
    body = response.json()
    assert "active_members" in body
    assert "sessions_this_week" in body
    assert "attendance_rate" in body
    assert "attendance_trend" in body


# ---------------------------------------------------------------------------
# AC7 — GET /dashboard/admin with member token → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_dashboard_member_returns_403(
    dashboard_repo: StubDashboardRepo,
) -> None:
    """A member token must receive 403 from GET /dashboard/admin."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(
            "/dashboard/admin",
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_dashboard_unauthenticated_returns_401(
    dashboard_repo: StubDashboardRepo,
) -> None:
    """No token must receive 401 from GET /dashboard/admin."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/dashboard/admin")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC8 — GET /dashboard/admin returns correct active member count
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_dashboard_active_member_count_is_correct(
    dashboard_repo: StubDashboardRepo,
) -> None:
    """active_members reflects only members whose membership_status is 'active'."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    dashboard_repo.seed_member(status="active")
    dashboard_repo.seed_member(status="active")
    dashboard_repo.seed_member(status="inactive")  # must NOT be counted

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/dashboard/admin")

    assert response.status_code == 200
    assert response.json()["active_members"] == 2


@pytest.mark.anyio
async def test_admin_dashboard_active_member_count_zero_when_no_members(
    dashboard_repo: StubDashboardRepo,
) -> None:
    """active_members is 0 when the member table is empty."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/dashboard/admin")

    assert response.status_code == 200
    assert response.json()["active_members"] == 0


# ---------------------------------------------------------------------------
# AC9 — attendance_trend > 0.0 when current 30-day rate > previous
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_dashboard_trend_positive_when_rate_improving(
    dashboard_repo: StubDashboardRepo,
) -> None:
    """attendance_trend > 0.0 when the current 30-day rate exceeds the previous."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    member = dashboard_repo.seed_member(status="active")

    # Previous period (31-60 days ago): 1 session, 0 attendees → rate = 0
    dashboard_repo.seed_session(TODAY - timedelta(days=45))
    # (no attendance seeded for old_session → rate 0 in previous period)

    # Current period (0-30 days ago): 1 session, member attended → rate > 0
    recent_session = dashboard_repo.seed_session(TODAY - timedelta(days=5))
    dashboard_repo.seed_attendance(recent_session["id"], member["id"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/dashboard/admin")

    assert response.status_code == 200
    assert response.json()["attendance_trend"] > 0.0


# ---------------------------------------------------------------------------
# AC10 — attendance_trend < 0.0 when current 30-day rate < previous
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_dashboard_trend_negative_when_rate_declining(
    dashboard_repo: StubDashboardRepo,
) -> None:
    """attendance_trend < 0.0 when the current 30-day rate is below the previous."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    member = dashboard_repo.seed_member(status="active")

    # Previous period (31-60 days ago): 1 session, member attended → rate > 0
    old_session = dashboard_repo.seed_session(TODAY - timedelta(days=45))
    dashboard_repo.seed_attendance(old_session["id"], member["id"])

    # Current period (0-30 days ago): 1 session, no attendees → rate = 0
    dashboard_repo.seed_session(TODAY - timedelta(days=5))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/dashboard/admin")

    assert response.status_code == 200
    assert response.json()["attendance_trend"] < 0.0


# ---------------------------------------------------------------------------
# AC11 — attendance_trend is a float
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_dashboard_trend_is_float(
    dashboard_repo: StubDashboardRepo,
) -> None:
    """attendance_trend must be a float (signed difference), not a string."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/dashboard/admin")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["attendance_trend"], float)


# ---------------------------------------------------------------------------
# AC12 — attendance_trend == 0.0 when both periods have no sessions
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_dashboard_trend_neutral_when_both_zero(
    dashboard_repo: StubDashboardRepo,
) -> None:
    """attendance_trend == 0.0 when both the current and previous periods have no sessions."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # No sessions seeded at all → both periods rate = 0.0, trend = 0.0
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/dashboard/admin")

    assert response.status_code == 200
    assert response.json()["attendance_trend"] == 0.0
