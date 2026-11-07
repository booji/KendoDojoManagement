"""A Member's Attendance history, served from PostgreSQL (#572).

test_attendance.py covers authorization against an in-memory repository; the
Session each record belongs to is joined in SQL, so these drive
GET /members/{id}/attendance over real rows.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from app.attendance.db_models import Attendance
from app.attendance.dependencies import get_attendance_repo
from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.main import app
from app.members.dependencies import get_current_member_id
from app.members.repository import SqlMemberRepository
from app.sessions.repository import SqlSessionInstanceRepository

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")
_SEGMENT = {"start_time": "19:00", "duration_minutes": 90, "type_ids": []}


@pytest.fixture(autouse=True)
def admin():
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _ADMIN
    app.dependency_overrides[get_current_member_id] = lambda: None
    app.dependency_overrides.pop(get_attendance_repo, None)
    yield
    app.dependency_overrides.clear()


async def _member(db) -> str:
    member = await SqlMemberRepository(db).add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": "Ai",
            "surname": "Sato",
            "join_date": "2025-01-01",
            "membership_status": "active",
        }
    )
    return member["id"]


async def _attended(db, member_id: str, title: str, date: str) -> str:
    instance = await SqlSessionInstanceRepository(db).add(
        {"title": title, "date": date, "segments": [_SEGMENT]}
    )
    await db.execute(
        insert(Attendance).values(
            id=str(uuid.uuid4()),
            session_id=instance["id"],
            member_id=member_id,
            checked_in_at=f"{date}T19:00:00+00:00",
            recorded_by=_ADMIN.sub,
        )
    )
    return instance["id"]


async def _history(member_id: str) -> list[dict]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{member_id}/attendance")
    assert response.status_code == 200, response.text
    return response.json()


async def test_each_record_carries_its_session_title_and_date(db_client) -> None:
    member = await _member(db_client)
    session = await _attended(db_client, member, "Thursday keiko", "2026-03-05")
    db_client.expire_all()

    [record] = await _history(member)

    assert record["session_id"] == session
    assert record["session_title"] == "Thursday keiko"
    assert record["session_date"] == "2026-03-05"
