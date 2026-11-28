"""Real date/time columns (#433) leave the API's JSON unchanged (#448).

test_date_time_contract.py proves it at the repository layer; this asserts the
JSON itself, served from PostgreSQL (db_client), byte for byte: dates as
'YYYY-MM-DD', times as 'HH:MM' (Postgres itself would say 'HH:MM:SS'), and
timestamps as ISO-8601 with a '+00:00' offset — the strings the app has
always written.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from app.attendance.db_models import Attendance
from app.attendance.dependencies import get_attendance_repo
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.schemas import AccountClaims
from app.grades.repository import SqlGradeRepository
from app.main import app
from app.members.dependencies import get_current_member_id
from app.members.repository import SqlMemberRepository
from app.sessions.repository import (
    SqlSessionInstanceRepository,
    SqlSessionTemplateRepository,
)

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")
_SEGMENT = {"start_time": "07:30", "duration_minutes": 90, "type_ids": []}
# As the app writes it: datetime.now(UTC).isoformat(), microseconds included.
_CHECKED_IN_AT = "2026-10-01T07:32:05.123456+00:00"
_PROMOTED_AT = "2026-01-15T00:00:00+00:00"


@pytest.fixture(autouse=True)
def admin():
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _ADMIN
    # conftest stubs these for stub-based tests; every response here must come
    # from the database.
    app.dependency_overrides.pop(get_attendance_repo, None)
    app.dependency_overrides.pop(get_current_member_id, None)
    yield
    app.dependency_overrides.clear()


async def _get(path: str):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(path)
    assert response.status_code == 200, response.text
    return response.json()


async def _member(session) -> str:
    member = await SqlMemberRepository(session).add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": "Ai",
            "surname": "Sato",
            "dob": date(2010, 2, 28),
            "join_date": date(2026, 1, 1),
        }
    )
    return member["id"]


async def _session(session) -> str:
    instance = await SqlSessionInstanceRepository(session).add(
        {"title": "Keiko", "date": "2026-10-01", "segments": [_SEGMENT]}
    )
    return instance["id"]


async def test_member_dates(db_client) -> None:
    member_id = await _member(db_client)
    db_client.expire_all()

    body = await _get(f"/members/{member_id}")

    assert (body["dob"], body["join_date"]) == ("2010-02-28", "2026-01-01")


async def test_session_template_dates_and_segment_times(db_client) -> None:
    template = await SqlSessionTemplateRepository(db_client).add(
        {
            "title": "Keiko",
            "start_date": "2026-09-01",
            "end_date": "2027-03-01",
            "recurrence": "weekly",
            "segments": [_SEGMENT],
        }
    )
    db_client.expire_all()

    body = await _get(f"/sessions/templates/{template['id']}")

    assert (body["start_date"], body["end_date"]) == ("2026-09-01", "2027-03-01")
    assert [s["start_time"] for s in body["segments"]] == ["07:30"]


async def test_session_list_date_and_segment_times(db_client) -> None:
    session_id = await _session(db_client)
    db_client.expire_all()

    body = await _get("/sessions?from=2026-10-01&to=2026-10-01")

    [listed] = [s for s in body if s["id"] == session_id]
    assert listed["date"] == "2026-10-01"
    # scheduled_at is the repository's, not the API's: SessionInstanceRead
    # drops it, and test_date_time_contract.py covers it there.
    assert "scheduled_at" not in listed
    assert [s["start_time"] for s in listed["segments"]] == ["07:30"]


async def test_attendance_checked_in_at(db_client) -> None:
    member_id = await _member(db_client)
    session_id = await _session(db_client)
    await db_client.execute(
        insert(Attendance).values(
            id=str(uuid.uuid4()),
            session_id=session_id,
            member_id=member_id,
            checked_in_at=_CHECKED_IN_AT,
            recorded_by=_ADMIN.sub,
        )
    )
    db_client.expire_all()

    body = await _get(f"/sessions/{session_id}/attendance")

    assert [a["checked_in_at"] for a in body] == [_CHECKED_IN_AT]


async def test_grade_history_promoted_at(db_client) -> None:
    member_id = await _member(db_client)
    await SqlGradeRepository(db_client).add_promotion(
        member_id, "SHODAN", "Shodan (1-dan)", None, _PROMOTED_AT
    )
    db_client.expire_all()

    body = await _get(f"/members/{member_id}/grades")

    assert [g["promoted_at"] for g in body] == [_PROMOTED_AT]
