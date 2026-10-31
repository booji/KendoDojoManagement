"""
Failing tests for issue #83 — attendance_count and is_checked_in inline on GET /sessions.

Backend acceptance criteria:
  - SessionInstanceRead gains `attendance_count: int = 0`
  - SessionInstanceRead gains `is_checked_in: bool = False`
  - GET /sessions populates attendance_count from the attendance table
  - GET /sessions populates is_checked_in for the authenticated member

NO real DB: the shared in-memory fakes stand in for the repositories.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.attendance.dependencies import (
    get_attendance_repo,
)
from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.main import app
from app.members.dependencies import get_current_member_id
from app.sessions.dependencies import (
    get_session_instance_repo,
    get_session_template_repo,
    get_session_type_repo,
)
from app.sessions.models import SessionInstanceRead
from tests.auth_support import sign_in
from tests.fake_repositories import (
    InMemoryAttendanceRepository,
    InMemorySessionInstanceRepository,
    InMemorySessionTemplateRepository,
    InMemorySessionTypeRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER = AccountClaims(sub="member-uuid", email="member@dojo.test", role="member")
# The Member record id behind _MEMBER's user. Attendance is keyed by Member id
# (#340), so it must differ from the Account id in the token for these tests to
# tell the two apart.
_MEMBER_ID = "member-record-uuid"


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def current_member_id() -> str:
    """_MEMBER's user resolves to their Member record; attendance is keyed by
    Member id (#340)."""
    app.dependency_overrides[get_current_member_id] = lambda: _MEMBER_ID
    return _MEMBER_ID


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def type_repo() -> InMemorySessionTypeRepository:
    repo = InMemorySessionTypeRepository([{"name": "General Training"}])
    app.dependency_overrides[get_session_type_repo] = lambda: repo
    return repo


@pytest.fixture()
def template_repo() -> InMemorySessionTemplateRepository:
    repo = InMemorySessionTemplateRepository()
    app.dependency_overrides[get_session_template_repo] = lambda: repo
    return repo


@pytest.fixture()
def instance_repo() -> InMemorySessionInstanceRepository:
    repo = InMemorySessionInstanceRepository()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


@pytest.fixture()
def attendance_repo() -> InMemoryAttendanceRepository:
    repo = InMemoryAttendanceRepository()
    app.dependency_overrides[get_attendance_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# Tests for model fields
# ---------------------------------------------------------------------------


def test_session_instance_read_has_attendance_count_field() -> None:
    """SessionInstanceRead must have an attendance_count field defaulting to 0."""
    instance = SessionInstanceRead(
        id=str(uuid.uuid4()),
        title="Test Session",
        date="2099-01-01",
        start_time="19:00",
        duration_minutes=90,
        segments=[
            {
                "start_time": "19:00",
                "duration_minutes": 90,
                "type_ids": [str(uuid.uuid4())],
            }
        ],
    )
    assert instance.attendance_count == 0


def test_session_instance_read_has_is_checked_in_field() -> None:
    """SessionInstanceRead must have an is_checked_in field defaulting to False."""
    instance = SessionInstanceRead(
        id=str(uuid.uuid4()),
        title="Test Session",
        date="2099-01-01",
        start_time="19:00",
        duration_minutes=90,
        segments=[
            {
                "start_time": "19:00",
                "duration_minutes": 90,
                "type_ids": [str(uuid.uuid4())],
            }
        ],
    )
    assert instance.is_checked_in is False


# ---------------------------------------------------------------------------
# Tests for GET /sessions endpoint
# ---------------------------------------------------------------------------


async def test_list_sessions_includes_attendance_count(
    type_repo, template_repo, instance_repo, attendance_repo
) -> None:
    """GET /sessions returns attendance_count reflecting the number of attendance records."""
    app.dependency_overrides[REQUIRE_MEMBER] = (
        _admin_override  # use admin for full view
    )

    type_id = (await type_repo.list())[0]["id"]

    # Seed one future session
    session = await instance_repo.add(
        {
            "title": "Keiko",
            "date": "2099-03-01",
            "segments": [
                {
                    "start_time": "19:00",
                    "duration_minutes": 90,
                    "type_ids": [type_id],
                }
            ],
        }
    )
    session_id = session["id"]

    # Seed two attendance records for that session
    await attendance_repo.check_in(session_id, "member-1", "admin-uuid")
    await attendance_repo.check_in(session_id, "member-2", "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/sessions")

    assert response.status_code == 200
    sessions = response.json()
    target = next(s for s in sessions if s["id"] == session_id)
    assert target["attendance_count"] == 2


async def test_list_sessions_includes_is_checked_in_for_member(
    type_repo, template_repo, instance_repo, attendance_repo
) -> None:
    """GET /sessions returns is_checked_in=true where the current member has checked in."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    type_id = (await type_repo.list())[0]["id"]

    # Seed two future sessions
    checked_in_session = await instance_repo.add(
        {
            "title": "Keiko",
            "date": "2099-04-01",
            "segments": [
                {
                    "start_time": "19:00",
                    "duration_minutes": 90,
                    "type_ids": [type_id],
                }
            ],
        }
    )
    not_checked_in_session = await instance_repo.add(
        {
            "title": "Keiko",
            "date": "2099-04-08",
            "segments": [
                {
                    "start_time": "19:00",
                    "duration_minutes": 90,
                    "type_ids": [type_id],
                }
            ],
        }
    )

    # Check in the member only to the first session
    await attendance_repo.check_in(checked_in_session["id"], _MEMBER_ID, _MEMBER_ID)

    token = sign_in(_MEMBER)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/sessions", cookies={"access_token": token})

    assert response.status_code == 200
    sessions = response.json()
    by_id = {s["id"]: s for s in sessions}

    assert by_id[checked_in_session["id"]]["is_checked_in"] is True
    assert by_id[not_checked_in_session["id"]]["is_checked_in"] is False


# ---------------------------------------------------------------------------
# GET /sessions must not query attendance once per session (#339)
# ---------------------------------------------------------------------------


class _CountingAttendanceRepo(InMemoryAttendanceRepository):
    """The attendance fake, counting per-session reads."""

    def __init__(self) -> None:
        super().__init__()
        self.per_session_calls = 0

    async def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        self.per_session_calls += 1
        return await super().list_for_session(session_id)


async def test_list_sessions_reads_attendance_in_one_call(
    type_repo, template_repo, instance_repo
) -> None:
    """GET /sessions must summarise attendance for every session at once.

    The per-session loop it replaces cost one query per session, each one an
    outer join against Member, to produce a count and a boolean.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    attendance_repo = _CountingAttendanceRepo()
    app.dependency_overrides[get_attendance_repo] = lambda: attendance_repo

    type_id = (await type_repo.list())[0]["id"]
    sessions = [
        await instance_repo.add(
            {
                "title": "Keiko",
                "date": f"2099-03-0{day}",
                "segments": [
                    {
                        "start_time": "19:00",
                        "duration_minutes": 90,
                        "type_ids": [type_id],
                    }
                ],
            }
        )
        for day in (1, 2, 3)
    ]
    await attendance_repo.check_in(sessions[0]["id"], _MEMBER_ID, _MEMBER.sub)
    await attendance_repo.check_in(sessions[0]["id"], "someone-else", "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/sessions")

    assert response.status_code == 200
    by_id = {s["id"]: s for s in response.json()}
    assert by_id[sessions[0]["id"]]["attendance_count"] == 2
    assert by_id[sessions[0]["id"]]["is_checked_in"] is True
    assert by_id[sessions[1]["id"]]["attendance_count"] == 0
    assert by_id[sessions[1]["id"]]["is_checked_in"] is False
    assert (
        attendance_repo.per_session_calls == 0
    ), "GET /sessions must not read attendance one session at a time"


async def test_admin_marked_member_sees_themselves_as_checked_in(
    type_repo, template_repo, instance_repo, attendance_repo
) -> None:
    """Being marked present by an admin counts as checked in for that member.

    Issue #340: the roster said the member was attending while their own
    session list said they were not, because self check-in wrote an Account id and
    admin marking wrote a Member id into the same column.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    type_id = (await type_repo.list())[0]["id"]
    session = await instance_repo.add(
        {
            "title": "Keiko",
            "date": "2099-05-01",
            "segments": [
                {"start_time": "19:00", "duration_minutes": 90, "type_ids": [type_id]}
            ],
        }
    )
    await attendance_repo.admin_mark_attended(session["id"], _MEMBER_ID, "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/sessions", cookies={"access_token": sign_in(_MEMBER)})

    assert response.status_code == 200, response.text
    target = next(s for s in response.json() if s["id"] == session["id"])
    assert target["is_checked_in"] is True
