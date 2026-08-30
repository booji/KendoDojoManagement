"""
Unit / integration tests for issue #9 — Attendance / Check-in.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  2. POST /sessions/{id}/checkin checks in the authenticated member
  3. A member cannot check in to a cancelled session
  4. GET /sessions/{id}/checkin-token generates a short-lived token (admin only)
  5. POST /checkin/{token} resolves token and checks in the authenticated member
  6. Expired or invalid token returns an appropriate error
  7. Admin can see a live list via GET /sessions/{id}/attendance
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.attendance.dependencies import (
    get_attendance_repo,
    get_checkin_token_repo,
    get_session_instance_repo,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.auth.token import encode_token
from app.main import app
from app.members.dependencies import get_current_member_id
from app.sessions.envelope import envelope_bounds
from app.settings.dependencies import get_dojo_settings_repo
from tests.fake_repositories import (
    InMemoryAttendanceRepository,
    InMemorySessionInstanceRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = UserClaims(
    sub="00000000-0000-0000-0000-000000000002",
    email="member@dojo.test",
    role="member",
    is_active=True,
)
_OTHER_MEMBER = UserClaims(
    sub="other-member-uuid", email="other@dojo.test", role="member", is_active=True
)

# The Member record id belonging to _MEMBER's user. attendance.member_id holds
# a Member id, never a User id (#340), so the two must differ here for the
# tests to be able to tell them apart.
_MEMBER_RECORD_ID = "00000000-0000-0000-0000-0000000000a2"

# Valid UUIDs for use in path params
_SOME_MEMBER_UUID = "00000000-0000-0000-0000-000000000099"
_NONEXISTENT_MEMBER_UUID = "00000000-0000-0000-0000-000000000000"


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


def _other_member_override():
    return _OTHER_MEMBER


def _member_token() -> str:
    return encode_token(_MEMBER)


def _admin_token() -> str:
    return encode_token(_ADMIN)


# ---------------------------------------------------------------------------
# Stub repositories
# ---------------------------------------------------------------------------


class _AttendanceSessionRepo(InMemorySessionInstanceRepository):
    """The session instance fake, with a seed() that speaks wall-clock times.

    A 30-minute session starting at ``now``, expressed as the segment that
    derives that envelope. The fake emits an end past midnight as raw
    hours-since-midnight with no 24-hour wrap -- a session seeded at 23:52
    ends at "24:22", not "00:22", which would place the end 23.5 hours before
    the start once ``envelope_bounds`` resolved it.
    """

    def seed(  # type: ignore[override]
        self, cancelled: bool = False, now: datetime | None = None
    ) -> dict[str, Any]:
        now = now or datetime.now()
        return super().seed(
            date=now.strftime("%Y-%m-%d"),
            cancelled=cancelled,
            segments=[
                {
                    "start_time": now.strftime("%H:%M"),
                    "duration_minutes": 30,
                    "type_ids": [],
                }
            ],
        )


class StubCheckinTokenRepo:
    """In-memory stand-in for a CheckinToken repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def create(self, session_id: str, expires_at: datetime) -> dict[str, Any]:
        token = str(uuid.uuid4())
        record = {
            "token": token,
            "session_id": session_id,
            "expires_at": expires_at.isoformat(),
        }
        self._store[token] = record
        return record

    async def get(self, token: str) -> dict[str, Any] | None:
        return self._store.get(token)

    async def redeem(self, token: str) -> dict[str, Any] | None:
        record = self._store.get(token)
        if record is None:
            return None
        if record.get("used_at") is not None:
            raise ValueError("Token already used")
        record["used_at"] = datetime.now(UTC).isoformat()
        return record

    def seed_expired(self, session_id: str) -> dict[str, Any]:
        """Seed an already-expired token for testing."""
        token = str(uuid.uuid4())
        record = {
            "token": token,
            "session_id": session_id,
            "expires_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        }
        self._store[token] = record
        return record


class StubDojoSettingsRepo:
    """In-memory stand-in for the dojo settings repository (check-in window
    defaults only — issue #192) so these tests never need the real DB."""

    def __init__(self) -> None:
        self._settings: dict[str, Any] = {
            "dojo_name": "My Dojo",
            "logo_url": None,
            "primary_colour": "#4F46E5",
            "checkin_window_before_minutes": 60,
            "checkin_window_after_minutes": 120,
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
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def session_repo() -> _AttendanceSessionRepo:
    repo = _AttendanceSessionRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


@pytest.fixture()
def attendance_repo() -> InMemoryAttendanceRepository:
    repo = InMemoryAttendanceRepository()
    app.dependency_overrides[get_attendance_repo] = lambda: repo
    return repo


@pytest.fixture()
def token_repo() -> StubCheckinTokenRepo:
    repo = StubCheckinTokenRepo()
    app.dependency_overrides[get_checkin_token_repo] = lambda: repo
    return repo


@pytest.fixture()
def settings_repo() -> StubDojoSettingsRepo:
    repo = StubDojoSettingsRepo()
    app.dependency_overrides[get_dojo_settings_repo] = lambda: repo
    return repo


@pytest.fixture(autouse=True)
def current_member_id() -> str:
    """Every attendance path resolves the caller to a Member id (#340), so the
    mapping is wired for every test in this module, not just the ones that
    name it. Tests needing a different caller override it again."""
    app.dependency_overrides[get_current_member_id] = lambda: _MEMBER_RECORD_ID
    return _MEMBER_RECORD_ID


# ---------------------------------------------------------------------------
# AC2 — POST /sessions/{id}/checkin
# ---------------------------------------------------------------------------


async def test_member_can_checkin_to_session(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/sessions/{session['id']}/checkin")

    # Body on failure: this assertion produced a bare `assert 403 == 200` once
    # under a full run and passed in isolation (#283). The session is seeded at
    # "now" against a 60-min-before / 120-min-after window, so neither
    # TOO_EARLY nor CLOSED is reachable here — without the response detail
    # there is no way to tell which 403 branch fired if it recurs.
    assert response.status_code == 200, response.text
    body = response.json()
    assert "id" in body
    assert body["session_id"] == session["id"]
    # The Member id, not the caller's User id (#340)
    assert body["member_id"] == _MEMBER_RECORD_ID
    assert "checked_in_at" in body
    assert body["recorded_by"] == _MEMBER.sub


@pytest.mark.parametrize(
    ("hour", "minute", "expected_start", "expected_end"),
    [
        (19, 0, "19:00", "19:30"),
        (23, 30, "23:30", "24:00"),
        (23, 52, "23:52", "24:22"),
        (23, 59, "23:59", "24:29"),
    ],
)
def test_seeded_session_envelope_never_ends_before_it_starts(
    session_repo: _AttendanceSessionRepo,
    hour: int,
    minute: int,
    expected_start: str,
    expected_end: str,
) -> None:
    """The stub must emit the non-wrapping end time production emits.

    Regression for #277: seed() formatted the end with strftime, so a 23:52
    start produced an end of "00:22" — a shape session_time_envelope never
    emits. envelope_bounds resolved it to 23.5 hours *before* the start, the
    window classified as CLOSED, and every check-in test failed with 403 for
    any run started in the last half hour before midnight.
    """
    at = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    session = session_repo.seed(cancelled=False, now=at)

    assert session["start_time"] == expected_start
    assert session["end_time"] == expected_end

    start, end = envelope_bounds(
        session["date"], session["start_time"], session["end_time"]
    )
    assert end - start == timedelta(minutes=30)


async def test_checkin_without_a_member_record_is_rejected(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """A user with no Member record has nothing to key attendance by (#340).

    Before the normalisation this stored the User id, which no roster, report
    or history query could resolve back to a person.
    """
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    app.dependency_overrides[get_current_member_id] = lambda: None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/sessions/{session['id']}/checkin")

    assert response.status_code == 403, response.text


async def test_unauthenticated_checkin_returns_401(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/sessions/{session['id']}/checkin")

    assert response.status_code == 401


async def test_checkin_nonexistent_session_returns_404(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    fake_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/sessions/{fake_id}/checkin")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC3 — Cannot check in to a cancelled session
# ---------------------------------------------------------------------------


async def test_member_cannot_checkin_to_cancelled_session(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=True)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/sessions/{session['id']}/checkin")

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# AC4 — GET /sessions/{id}/checkin-token (admin only)
# ---------------------------------------------------------------------------


async def test_admin_can_generate_checkin_token(
    session_repo: _AttendanceSessionRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{session['id']}/checkin-token")

    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert isinstance(body["token"], str)
    assert "expires_at" in body


async def test_member_cannot_generate_checkin_token(
    session_repo: _AttendanceSessionRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(
            f"/sessions/{session['id']}/checkin-token",
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


async def test_generate_token_for_nonexistent_session(
    session_repo: _AttendanceSessionRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{fake_id}/checkin-token")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC5 — POST /checkin/{token}
# ---------------------------------------------------------------------------


async def test_member_can_checkin_via_token(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    token_repo: StubCheckinTokenRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    token_record = await token_repo.create(session["id"], expires_at)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/checkin/{token_record['token']}")

    assert response.status_code == 200
    body = response.json()
    assert "id" in body
    assert body["session_id"] == session["id"]
    assert body["member_id"] == _MEMBER_RECORD_ID
    assert "checked_in_at" in body


async def test_unauthenticated_token_checkin_returns_401(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    token_repo: StubCheckinTokenRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    token_record = await token_repo.create(session["id"], expires_at)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/checkin/{token_record['token']}")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC6 — Expired / invalid token
# ---------------------------------------------------------------------------


async def test_expired_token_returns_410(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    token_repo: StubCheckinTokenRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    expired = token_repo.seed_expired(session["id"])
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/checkin/{expired['token']}")

    assert response.status_code == 410


async def test_invalid_token_returns_401(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    token_repo: StubCheckinTokenRepo,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/checkin/this-token-does-not-exist")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC7 — GET /sessions/{id}/attendance (admin only)
# ---------------------------------------------------------------------------


async def test_admin_can_list_session_attendance(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # Seed two check-ins directly via the stub repo
    await attendance_repo.check_in(session["id"], "member-1", "self")
    await attendance_repo.check_in(session["id"], "member-2", "self")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{session['id']}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2
    member_ids = {r["member_id"] for r in body}
    assert "member-1" in member_ids
    assert "member-2" in member_ids


async def test_member_cannot_list_attendance(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(
            f"/sessions/{session['id']}/attendance",
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Issue #10 AC1 — POST /sessions/{id}/attendance (admin marks member attended)
# ---------------------------------------------------------------------------


async def test_admin_mark_attended_returns_201(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/attendance",
            json={"member_id": _SOME_MEMBER_UUID},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == session["id"]
    assert body["member_id"] == _SOME_MEMBER_UUID
    assert body["recorded_by"] == _ADMIN.sub


async def test_admin_mark_attended_nonexistent_session_returns_404(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{fake_id}/attendance",
            json={"member_id": _SOME_MEMBER_UUID},
        )

    assert response.status_code == 404


async def test_admin_mark_attended_missing_member_id_returns_422(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/attendance",
            json={},
        )

    assert response.status_code == 422


async def test_member_cannot_admin_mark_attended(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/attendance",
            json={"member_id": "some-member-uuid"},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Issue #10 AC2 — DELETE /sessions/{id}/attendance/{member_id}
# ---------------------------------------------------------------------------


async def test_admin_remove_attendance_returns_204(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)
    await attendance_repo.admin_mark_attended(
        session["id"], _SOME_MEMBER_UUID, "admin-uuid"
    )
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(
            f"/sessions/{session['id']}/attendance/{_SOME_MEMBER_UUID}"
        )

    assert response.status_code == 204


async def test_admin_remove_attendance_not_found_returns_404(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(
            f"/sessions/{session['id']}/attendance/{_NONEXISTENT_MEMBER_UUID}"
        )

    assert response.status_code == 404


async def test_member_cannot_remove_attendance(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(
            f"/sessions/{session['id']}/attendance/{_SOME_MEMBER_UUID}",
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Issue #10 AC3 — POST /sessions/{id}/visitors (admin adds visitor)
# ---------------------------------------------------------------------------


async def test_admin_add_visitor_returns_201(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/visitors",
            json={"visitor_name": "John Guest"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == session["id"]
    assert body["visitor_name"] == "John Guest"
    assert body["member_id"] is None


async def test_admin_add_visitor_nonexistent_session_returns_404(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{fake_id}/visitors",
            json={"visitor_name": "John Guest"},
        )

    assert response.status_code == 404


async def test_admin_add_visitor_missing_name_returns_422(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/visitors",
            json={},
        )

    assert response.status_code == 422


async def test_member_cannot_add_visitor(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/visitors",
            json={"visitor_name": "John Guest"},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Issue #10 AC4 — GET /sessions/{id}/attendance returns members AND visitors
# ---------------------------------------------------------------------------


async def test_session_attendance_includes_visitors(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    await attendance_repo.admin_mark_attended(session["id"], "member-1", "admin-uuid")
    await attendance_repo.add_visitor(session["id"], "Visitor One", "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{session['id']}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2

    member_records = [r for r in body if r.get("member_id") is not None]
    visitor_records = [r for r in body if r.get("member_id") is None]

    assert len(member_records) == 1
    assert len(visitor_records) == 1
    assert visitor_records[0]["visitor_name"] == "Visitor One"


async def test_attendance_record_has_visitor_name_field(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    """Each record in the list exposes visitor_name (nullable) for the new AttendanceReadV2 shape."""
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    await attendance_repo.admin_mark_attended(session["id"], "member-1", "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{session['id']}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    # member records have visitor_name=null
    assert "visitor_name" in body[0]
    assert body[0]["visitor_name"] is None


# ---------------------------------------------------------------------------
# Issue #10 AC5 — GET /members/{id}/attendance (member's history)
# ---------------------------------------------------------------------------


async def test_admin_can_get_any_member_attendance_history(
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = (
        _admin_override  # admin satisfies REQUIRE_MEMBER
    )
    # Admin bypasses the caller→member mapping entirely
    app.dependency_overrides[get_current_member_id] = lambda: None

    # Seed attendance records for a member
    session_id = str(uuid.uuid4())
    await attendance_repo.admin_mark_attended(session_id, _MEMBER.sub, "admin-uuid")
    await attendance_repo.admin_mark_attended(session_id, _MEMBER.sub, "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{_MEMBER.sub}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert all(r["member_id"] == _MEMBER.sub for r in body)


async def test_member_can_get_own_attendance_history(
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    # The caller's member record is the one named in the URL
    app.dependency_overrides[get_current_member_id] = lambda: _MEMBER.sub

    session_id = str(uuid.uuid4())
    await attendance_repo.admin_mark_attended(session_id, _MEMBER.sub, "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{_MEMBER.sub}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1


# ---------------------------------------------------------------------------
# Issue #10 AC6 — Member cannot access another member's attendance history
# ---------------------------------------------------------------------------


async def test_own_history_includes_a_self_checkin(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """Checking yourself in must show up in your own attendance history (#340).

    It did not while self check-in wrote the User id and the history query
    read by Member id.
    """
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.post(f"/sessions/{session['id']}/checkin")).status_code == 200
        response = await c.get(f"/members/{_MEMBER_RECORD_ID}/attendance")

    assert response.status_code == 200, response.text
    assert [r["session_id"] for r in response.json()] == [session["id"]]


async def test_member_cannot_get_other_member_attendance_history(
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _other_member_override
    # _OTHER_MEMBER's caller maps to a different member id, not _MEMBER.sub
    app.dependency_overrides[get_current_member_id] = lambda: _OTHER_MEMBER.sub

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{_MEMBER.sub}/attendance")

    assert response.status_code == 403


async def test_unauthenticated_cannot_get_member_attendance_history() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{_MEMBER.sub}/attendance")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Issue #79 — GET /sessions/{id}/attendance includes display_name
# ---------------------------------------------------------------------------


async def test_attendance_list_includes_display_name_for_member(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    """AC1+AC2: member records have display_name = member's full_name."""
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # The name the SQL implementation's outer join against Member would resolve
    attendance_repo.display_names["member-1"] = "Alice Kendo"
    await attendance_repo.admin_mark_attended(session["id"], "member-1", "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{session['id']}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["display_name"] == "Alice Kendo"


async def test_attendance_list_display_name_null_for_visitor(
    session_repo: _AttendanceSessionRepo,
    attendance_repo: InMemoryAttendanceRepository,
) -> None:
    """AC3: visitor records have display_name = null."""
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    await attendance_repo.add_visitor(session["id"], "Drop-in Guest", "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{session['id']}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["display_name"] is None


# ---------------------------------------------------------------------------
# Batch attendance summary (#339)
# ---------------------------------------------------------------------------


async def test_summary_for_sessions_counts_and_flags_in_one_call() -> None:
    """summary_for_sessions returns, per session, the attendance count and
    whether the given member is among those attending."""
    repo = InMemoryAttendanceRepository()
    await repo.check_in("s1", "member-1", "member-1")
    await repo.check_in("s1", "member-2", "member-2")
    await repo.check_in("s2", "member-2", "member-2")
    await repo.check_in("s3", "member-1", "member-1")

    summary = await repo.summary_for_sessions(["s1", "s2", "unknown"], "member-1")

    assert summary["s1"] == {"attendance_count": 2, "is_checked_in": True}
    assert summary["s2"] == {"attendance_count": 1, "is_checked_in": False}
    assert summary["unknown"] == {"attendance_count": 0, "is_checked_in": False}
    assert "s3" not in summary, "only the requested sessions are summarised"
