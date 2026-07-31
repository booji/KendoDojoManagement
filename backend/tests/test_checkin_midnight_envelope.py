"""
Regression tests for issue #206 — check-in 500s when a session's segment
envelope runs to/past midnight, producing a "24:xx" end_time.

`session_time_envelope()` returns the envelope end as a raw "HH:MM" string with
no 24-hour wrap, so a segment past midnight yields "24:15", "25:00", etc. The
attendance check-in path parsed that with ``datetime.strptime(..., "%H:%M")``,
which only accepts hours 00-23 and therefore raised ValueError -> 500.

The fix mirrors the iCal path (#204): build the datetimes as timedelta offsets
from midnight so hours >= 24 roll into the following day.

Uses the StubRepository pattern — NO real DB — mirroring
test_checkin_window_endpoint.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.attendance.dependencies import (
    get_attendance_repo,
    get_session_instance_repo,
)
from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from app.settings.dependencies import get_dojo_settings_repo

_MEMBER = UserClaims(
    sub="00000000-0000-0000-0000-000000000002",
    email="member@dojo.test",
    role="member",
    is_active=True,
)


def _member_override():
    return _MEMBER


# ---------------------------------------------------------------------------
# Stub repositories — raw seed that can place the envelope past midnight
# ---------------------------------------------------------------------------


class StubSessionInstanceRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    def seed_raw(self, date_str: str, start_time: str, end_time: str) -> dict[str, Any]:
        """Seed a session with explicit envelope strings, allowing an end_time
        of "24:15" / "25:00" etc. that a segment running past midnight yields."""
        new_id = str(uuid.uuid4())
        record = {
            "id": new_id,
            "date": date_str,
            "start_time": start_time,
            "end_time": end_time,
            "cancelled": False,
        }
        self._store[new_id] = record
        return record


class StubAttendanceRepo:
    def __init__(self) -> None:
        self._store: list[dict[str, Any]] = []

    async def check_in(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "member_id": member_id,
            "checked_in_at": datetime.now().isoformat(),
            "recorded_by": recorded_by,
        }
        self._store.append(record)
        return record

    async def get_by_session_member(
        self, session_id: str, member_id: str
    ) -> dict[str, Any] | None:
        for r in self._store:
            if r["session_id"] == session_id and r.get("member_id") == member_id:
                return r
        return None


class StubDojoSettingsRepo:
    async def get(self) -> dict[str, Any]:
        return {
            "dojo_name": "My Dojo",
            "logo_url": None,
            "primary_colour": "#4F46E5",
            "checkin_window_before_minutes": 60,
            "checkin_window_after_minutes": 120,
        }


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def session_repo() -> StubSessionInstanceRepo:
    repo = StubSessionInstanceRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


@pytest.fixture()
def attendance_repo() -> StubAttendanceRepo:
    repo = StubAttendanceRepo()
    app.dependency_overrides[get_attendance_repo] = lambda: repo
    return repo


@pytest.fixture()
def settings_repo() -> StubDojoSettingsRepo:
    repo = StubDojoSettingsRepo()
    app.dependency_overrides[get_dojo_settings_repo] = lambda: repo
    return repo


async def _post_checkin(session_id: str) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        return await c.post(f"/sessions/{session_id}/checkin")


# ---------------------------------------------------------------------------
# Pure helper — the actual crash site
# ---------------------------------------------------------------------------


def test_envelope_datetimes_rolls_end_past_midnight() -> None:
    """An envelope end of "24:15" must roll into 00:15 the following day rather
    than raising ValueError."""
    from app.sessions.envelope import envelope_bounds

    start, end = envelope_bounds("2026-07-09", "22:00", "24:15")

    assert start == datetime(2026, 7, 9, 22, 0)
    assert end == datetime(2026, 7, 10, 0, 15)


def test_envelope_datetimes_same_day_unchanged() -> None:
    """A normal same-day envelope is unaffected."""
    from app.sessions.envelope import envelope_bounds

    start, end = envelope_bounds("2026-07-09", "18:00", "20:00")

    assert start == datetime(2026, 7, 9, 18, 0)
    assert end == datetime(2026, 7, 9, 20, 0)


# ---------------------------------------------------------------------------
# Endpoint regression — must not 500
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_checkin_past_midnight_envelope_does_not_500(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """A session whose envelope ends at "24:15" must be handled gracefully
    (200 inside the window, or a 4xx window response) — never a 500."""
    # Anchor the session so that "now" sits comfortably inside the envelope:
    # start one hour ago, end well past midnight relative to that date.
    now = datetime.now()
    start = now - timedelta(hours=1)
    date_str = start.strftime("%Y-%m-%d")
    start_time = start.strftime("%H:%M")
    # Force an end that lands the following day expressed as >= 24h.
    end_of_day = start.replace(hour=0, minute=0) + timedelta(days=1, minutes=15)
    end_minutes = round(
        (end_of_day - start.replace(hour=0, minute=0)).total_seconds() / 60
    )
    end_time = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
    assert int(end_time.split(":")[0]) >= 24  # guard: envelope really is past midnight

    session = session_repo.seed_raw(date_str, start_time, end_time)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code != 500
    assert response.status_code == 200
