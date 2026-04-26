"""
Failing tests for issue #83 — attendance_count and is_checked_in inline on GET /sessions.

Backend acceptance criteria:
  - SessionInstanceRead gains `attendance_count: int = 0`
  - SessionInstanceRead gains `is_checked_in: bool = False`
  - GET /sessions populates attendance_count from the attendance table
  - GET /sessions populates is_checked_in for the authenticated member

Uses StubRepository pattern — NO real DB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

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
# Stub repositories
# ---------------------------------------------------------------------------


class StubSessionTypeRepo:
    def __init__(self) -> None:
        type_id = str(uuid.uuid4())
        self._store: dict[str, dict[str, Any]] = {
            type_id: {"id": type_id, "name": "General Training", "colour": None}
        }

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def get_by_name(self, name: str) -> dict[str, Any] | None:
        for item in self._store.values():
            if item["name"] == name:
                return item
        return None

    async def add(self, name: str) -> dict[str, Any]:
        existing = await self.get_by_name(name)
        if existing:
            raise ValueError(f"Session type '{name}' already exists")
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "name": name, "colour": None}
        self._store[new_id] = record
        return record


class StubSessionTemplateRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def get(self, template_id: str) -> dict[str, Any] | None:
        return self._store.get(template_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, **data}
        self._store[new_id] = record
        return record


class StubSessionInstanceRepo:
    """In-memory stand-in for a SessionInstance repository (sessions context)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def list_upcoming(self, as_of=None) -> list[dict[str, Any]]:
        from datetime import date

        now = as_of or date.today()
        return [
            s
            for s in self._store.values()
            if not s.get("cancelled", False) and date.fromisoformat(s["date"]) >= now
        ]

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "cancelled": False, **data}
        self._store[new_id] = record
        return record

    async def cancel(self, instance_id: str) -> dict[str, Any] | None:
        record = self._store.get(instance_id)
        if record is None:
            return None
        record["cancelled"] = True
        return record


class StubAttendanceRepo:
    """In-memory stand-in for an Attendance repository."""

    def __init__(self) -> None:
        self._store: list[dict[str, Any]] = []

    async def check_in(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "member_id": member_id,
            "checked_in_at": datetime.now(UTC).isoformat(),
            "recorded_by": recorded_by,
        }
        self._store.append(record)
        return record

    async def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return [r for r in self._store if r["session_id"] == session_id]

    async def get_by_session_member(
        self, session_id: str, member_id: str
    ) -> dict[str, Any] | None:
        for r in self._store:
            if r["session_id"] == session_id and r.get("member_id") == member_id:
                return r
        return None

    async def count_for_sessions(
        self, session_ids: list[str]
    ) -> dict[str, int]:
        """Return a mapping of session_id -> attendance count."""
        result: dict[str, int] = {sid: 0 for sid in session_ids}
        for r in self._store:
            sid = r["session_id"]
            if sid in result:
                result[sid] += 1
        return result

    async def member_checkins_for_sessions(
        self, session_ids: list[str], member_id: str
    ) -> set[str]:
        """Return the set of session_ids where the given member has checked in."""
        return {
            r["session_id"]
            for r in self._store
            if r["session_id"] in session_ids and r.get("member_id") == member_id
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def type_repo() -> StubSessionTypeRepo:
    repo = StubSessionTypeRepo()
    app.dependency_overrides[get_session_type_repo] = lambda: repo
    return repo


@pytest.fixture()
def template_repo() -> StubSessionTemplateRepo:
    repo = StubSessionTemplateRepo()
    app.dependency_overrides[get_session_template_repo] = lambda: repo
    return repo


@pytest.fixture()
def instance_repo() -> StubSessionInstanceRepo:
    repo = StubSessionInstanceRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


@pytest.fixture()
def attendance_repo() -> StubAttendanceRepo:
    repo = StubAttendanceRepo()
    app.dependency_overrides[get_attendance_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# Tests for model fields
# ---------------------------------------------------------------------------


def test_session_instance_read_has_attendance_count_field() -> None:
    """SessionInstanceRead must have an attendance_count field defaulting to 0."""
    instance = SessionInstanceRead(
        id=str(uuid.uuid4()),
        session_type_id=str(uuid.uuid4()),
        date="2099-01-01",
        start_time="19:00",
        duration_minutes=90,
    )
    assert instance.attendance_count == 0


def test_session_instance_read_has_is_checked_in_field() -> None:
    """SessionInstanceRead must have an is_checked_in field defaulting to False."""
    instance = SessionInstanceRead(
        id=str(uuid.uuid4()),
        session_type_id=str(uuid.uuid4()),
        date="2099-01-01",
        start_time="19:00",
        duration_minutes=90,
    )
    assert instance.is_checked_in is False


# ---------------------------------------------------------------------------
# Tests for GET /sessions endpoint
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_sessions_includes_attendance_count(
    type_repo, template_repo, instance_repo, attendance_repo
) -> None:
    """GET /sessions returns attendance_count reflecting the number of attendance records."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override  # use admin for full view

    type_id = list(type_repo._store.keys())[0]

    # Seed one future session
    session = await instance_repo.add(
        {
            "session_type_id": type_id,
            "date": "2099-03-01",
            "start_time": "19:00",
            "duration_minutes": 90,
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


@pytest.mark.anyio
async def test_list_sessions_includes_is_checked_in_for_member(
    type_repo, template_repo, instance_repo, attendance_repo
) -> None:
    """GET /sessions returns is_checked_in=true where the current member has checked in."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    type_id = list(type_repo._store.keys())[0]

    # Seed two future sessions
    checked_in_session = await instance_repo.add(
        {
            "session_type_id": type_id,
            "date": "2099-04-01",
            "start_time": "19:00",
            "duration_minutes": 90,
        }
    )
    not_checked_in_session = await instance_repo.add(
        {
            "session_type_id": type_id,
            "date": "2099-04-08",
            "start_time": "19:00",
            "duration_minutes": 90,
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
