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

import pytest
from httpx import ASGITransport, AsyncClient

from app.attendance.dependencies import (
    get_attendance_repo,
)
from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.auth.token import encode_token
from app.main import app
from app.sessions.dependencies import (
    get_session_instance_repo,
    get_session_template_repo,
    get_session_type_repo,
)
from app.sessions.models import SessionInstanceRead
from tests.fake_repositories import (
    InMemoryAttendanceRepository,
    InMemorySessionInstanceRepository,
    InMemorySessionTemplateRepository,
    InMemorySessionTypeRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = UserClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)
_MEMBER_ID = "member-uuid"


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
        transport=ASGITransport(app=app), base_url="http://test"
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

    token = encode_token(_MEMBER)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions", cookies={"access_token": token})

    assert response.status_code == 200
    sessions = response.json()
    by_id = {s["id"]: s for s in sessions}

    assert by_id[checked_in_session["id"]]["is_checked_in"] is True
    assert by_id[not_checked_in_session["id"]]["is_checked_in"] is False
