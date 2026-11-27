"""
Unit / integration tests for issue #192 — check-in window enforcement on
POST /sessions/{id}/checkin using dojo-wide default minutes.

Scope: DOJO-WIDE DEFAULTS ONLY (checkin_window_before_minutes /
checkin_window_after_minutes on DojoSettings). Per-session override columns
are a separate, later slice and are out of scope here.

Uses StubRepository pattern — NO real DB — mirroring test_attendance.py.

Acceptance criteria exercised here:
  4. POST /sessions/{id}/checkin enforces the window using dojo defaults:
     200 inside; 403 with structured detail too_early/closed plus the
     relevant boundary time when outside.
  5. "Now" is evaluated against server-local time (we drive this by seeding
     sessions relative to datetime.now(), not by mocking the clock).
  6. Admin mark-attended (POST /sessions/{id}/attendance) remains
     UNCONSTRAINED by the window. The admin one-off token endpoint that also
     bypassed it (POST /checkin/{token}) has since been retired — the one
     check-in link a session has now routes through the window like any
     other member check-in.
  Preserves existing 404 / 409 already-checked-in / 409 cancelled behaviour.

The session dict handed back by the (stubbed) session repo now needs to
expose a start/end envelope so the endpoint can evaluate the window. We
seed `date` (YYYY-MM-DD) plus `start_time`/`end_time` ("HH:MM") — the same
shape `session_time_envelope()` already produces elsewhere in the codebase.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time
from httpx import ASGITransport, AsyncClient

from app.attendance.dependencies import (
    get_attendance_repo,
    get_session_instance_repo,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.schemas import AccountClaims
from app.main import app
from app.settings.dependencies import get_dojo_settings_repo
from tests.fake_repositories import (
    InMemoryAttendanceRepository,
    InMemorySessionInstanceRepository,
)

# ---------------------------------------------------------------------------
# Defaults under test (issue #192 AC2)
# ---------------------------------------------------------------------------

_DEFAULT_BEFORE_MINUTES = 60
_DEFAULT_AFTER_MINUTES = 120

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER = AccountClaims(
    sub="00000000-0000-0000-0000-000000000002",
    email="member@dojo.test",
    role="member",
)
_SOME_MEMBER_UUID = "00000000-0000-0000-0000-000000000099"


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


# ---------------------------------------------------------------------------
# Stub repositories
# ---------------------------------------------------------------------------


def _split_date_time(dt: datetime) -> tuple[str, str]:
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


class _WindowSessionRepo(InMemorySessionInstanceRepository):
    """The session instance fake, with a seed() that speaks wall-clock times.

    Seeds the single segment whose derived envelope spans [start, end), so
    window enforcement evaluates a record derived the way production derives
    it. Defaults to a session happening right now, comfortably inside any sane
    window.
    """

    def seed(  # type: ignore[override]
        self,
        cancelled: bool = False,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        now = datetime.now()
        start = start if start is not None else now
        end = end if end is not None else now + timedelta(minutes=60)
        date_str, start_time = _split_date_time(start)
        assert start.date() == end.date(), "test sessions must not cross midnight"

        return super().seed(
            date=date_str,
            cancelled=cancelled,
            segments=[
                {
                    "start_time": start_time,
                    "duration_minutes": round((end - start).total_seconds() / 60),
                    "type_ids": [],
                }
            ],
        )


class StubDojoSettingsRepo:
    """In-memory stand-in for the dojo settings repository, carrying the new
    check-in window default minutes (issue #192 AC2)."""

    def __init__(
        self,
        before_minutes: int = _DEFAULT_BEFORE_MINUTES,
        after_minutes: int = _DEFAULT_AFTER_MINUTES,
    ) -> None:
        self._settings: dict[str, Any] = {
            "dojo_name": "My Dojo",
            "logo_url": None,
            "primary_colour": "#4F46E5",
            "checkin_window_before_minutes": before_minutes,
            "checkin_window_after_minutes": after_minutes,
        }

    async def get(self) -> dict[str, Any]:
        return dict(self._settings)

    async def update(self, data: dict[str, Any]) -> dict[str, Any]:
        self._settings.update(data)
        return dict(self._settings)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def frozen_clock():
    """Pin the wall clock to a fixed midday so sessions seeded relative to
    ``datetime.now()`` (e.g. now + 90 min for the too-early cases) never roll
    across midnight. Without this the suite is flaky when run within ~90 min of
    local midnight — the endpoint and the stub both read the same frozen now, so
    the window maths stays deterministic regardless of when the tests run (#208).
    """
    with freeze_time("2026-07-15 12:00:00"):
        yield


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def session_repo() -> _WindowSessionRepo:
    repo = _WindowSessionRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


@pytest.fixture()
def attendance_repo() -> InMemoryAttendanceRepository:
    repo = InMemoryAttendanceRepository()
    app.dependency_overrides[get_attendance_repo] = lambda: repo
    return repo


@pytest.fixture()
def settings_repo() -> StubDojoSettingsRepo:
    repo = StubDojoSettingsRepo()
    app.dependency_overrides[get_dojo_settings_repo] = lambda: repo
    return repo


async def _post_checkin(session_id: str) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        return await c.post(f"/sessions/{session_id}/checkin")


# ---------------------------------------------------------------------------
# AC4/AC5 — 200 inside the window
# ---------------------------------------------------------------------------


async def test_checkin_inside_window_returns_200(
    session_repo: _WindowSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """A session happening right now (comfortably inside the default
    60-before/120-after window) allows check-in."""
    now = datetime.now()
    session = session_repo.seed(
        cancelled=False, start=now, end=now + timedelta(minutes=30)
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# AC4 — 403 too_early
# ---------------------------------------------------------------------------


async def test_checkin_before_window_returns_403_too_early(
    session_repo: _WindowSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """A session starting well beyond the before-minutes default (60) is
    too early to check in to."""
    now = datetime.now()
    start = now + timedelta(minutes=_DEFAULT_BEFORE_MINUTES + 30)
    session = session_repo.seed(
        cancelled=False, start=start, end=start + timedelta(minutes=60)
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["reason"] == "too_early"
    assert "opens_at" in detail


async def test_checkin_too_early_detail_reports_correct_open_boundary(
    session_repo: _WindowSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """The reported opens_at boundary equals session_start - before_minutes."""
    now = datetime.now()
    start = now + timedelta(minutes=90)  # beyond the 60-minute default
    session = session_repo.seed(
        cancelled=False, start=start, end=start + timedelta(minutes=60)
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 403
    # The seeded session only carries minute-granularity start_time/end_time
    # (see _WindowSessionRepo.seed / _split_date_time), so the boundary
    # the endpoint reports is necessarily truncated to the minute too.
    truncated_start = start.replace(second=0, microsecond=0)
    expected_open = truncated_start - timedelta(minutes=_DEFAULT_BEFORE_MINUTES)
    reported_open = datetime.fromisoformat(response.json()["detail"]["opens_at"])
    assert reported_open == expected_open


# ---------------------------------------------------------------------------
# AC4 — 403 closed
# ---------------------------------------------------------------------------


async def test_checkin_after_window_returns_403_closed(
    session_repo: _WindowSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """A session that ended well beyond the after-minutes default (120) is
    closed for check-in."""
    now = datetime.now()
    end = now - timedelta(minutes=_DEFAULT_AFTER_MINUTES + 30)
    start = end - timedelta(minutes=60)
    session = session_repo.seed(cancelled=False, start=start, end=end)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["reason"] == "closed"
    assert "closes_at" in detail


async def test_checkin_closed_detail_reports_correct_close_boundary(
    session_repo: _WindowSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """The reported closes_at boundary equals session_end + after_minutes."""
    now = datetime.now()
    end = now - timedelta(minutes=150)  # beyond the 120-minute default
    start = end - timedelta(minutes=60)
    session = session_repo.seed(cancelled=False, start=start, end=end)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 403
    # The seeded session only carries minute-granularity start_time/end_time
    # (see _WindowSessionRepo.seed / _split_date_time), so the boundary
    # the endpoint reports is necessarily truncated to the minute too.
    truncated_end = end.replace(second=0, microsecond=0)
    expected_close = truncated_end + timedelta(minutes=_DEFAULT_AFTER_MINUTES)
    reported_close = datetime.fromisoformat(response.json()["detail"]["closes_at"])
    assert reported_close == expected_close


# ---------------------------------------------------------------------------
# AC6 — Admin mark-attended bypasses the window entirely
# ---------------------------------------------------------------------------


async def test_admin_mark_attended_bypasses_window_when_too_early(
    session_repo: _WindowSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """POST /sessions/{id}/attendance (admin mark-attended) must succeed even
    for a session far outside the check-in window."""
    now = datetime.now()
    start = now + timedelta(hours=6)  # nowhere near the window
    session = session_repo.seed(
        cancelled=False, start=start, end=start + timedelta(minutes=60)
    )
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/attendance",
            json={"member_id": _SOME_MEMBER_UUID},
        )

    assert response.status_code == 201


async def test_admin_mark_attended_bypasses_window_when_closed(
    session_repo: _WindowSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """POST /sessions/{id}/attendance (admin mark-attended) must succeed even
    for a session long closed for self check-in."""
    now = datetime.now()
    end = now - timedelta(hours=6)
    start = end - timedelta(minutes=60)
    session = session_repo.seed(cancelled=False, start=start, end=end)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/attendance",
            json={"member_id": _SOME_MEMBER_UUID},
        )

    assert response.status_code == 201


# ---------------------------------------------------------------------------
# Preserve existing behaviour — 404 / 409 already-checked-in / 409 cancelled
# ---------------------------------------------------------------------------


async def test_checkin_nonexistent_session_still_returns_404(
    session_repo: _WindowSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    fake_id = str(uuid.uuid4())

    response = await _post_checkin(fake_id)

    assert response.status_code == 404


async def test_checkin_cancelled_session_still_returns_409_even_inside_window(
    session_repo: _WindowSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    now = datetime.now()
    session = session_repo.seed(
        cancelled=True, start=now, end=now + timedelta(minutes=30)
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 409


async def test_checkin_already_checked_in_still_returns_409_inside_window(
    session_repo: _WindowSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    now = datetime.now()
    session = session_repo.seed(
        cancelled=False, start=now, end=now + timedelta(minutes=30)
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    first = await _post_checkin(session["id"])
    assert first.status_code == 200

    second = await _post_checkin(session["id"])
    assert second.status_code == 409
