"""Headcount per Session on the Charts tab (#561).

One point per held Session in the From/To range, split into Members and
Visitors. A Session under Cancellation is not held. Served from PostgreSQL
(db_client) through GET /reports/headcount.

Other tests leave Sessions in the shared database, so each test looks only at
the Sessions it seeds.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.attendance.repository import SqlAttendanceRepository
from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.main import app
from app.members.repository import SqlMemberRepository
from app.sessions.repository import SqlSessionInstanceRepository

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")
_SEGMENT = {"start_time": "19:00", "duration_minutes": 90, "type_ids": []}
_RANGE = {"date_from": "2026-03-01", "date_to": "2026-03-31"}


@pytest.fixture
def as_admin(db_client):
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN
    yield
    app.dependency_overrides.pop(REQUIRE_ADMIN, None)


async def _get(params: dict[str, str] = _RANGE, **kwargs):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        return await c.get("/reports/headcount", params=params, **kwargs)


async def _points(params: dict[str, str] = _RANGE) -> list[dict]:
    response = await _get(params)
    assert response.status_code == 200, response.text
    return response.json()


async def _member(db, status: str = "active") -> str:
    member = await SqlMemberRepository(db).add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": "Ai",
            "surname": "Sato",
            "join_date": "2025-01-01",
            "membership_status": status,
        }
    )
    return member["id"]


async def _session(db, date: str) -> str:
    instance = await SqlSessionInstanceRepository(db).add(
        {"title": "Keiko", "date": date, "segments": [_SEGMENT]}
    )
    return instance["id"]


async def _attend(db, session_id: str, member_id: str) -> None:
    await SqlAttendanceRepository(db).admin_mark_attended(
        session_id, member_id, _ADMIN.sub
    )


async def _visitor(db, session_id: str) -> None:
    await SqlAttendanceRepository(db).add_visitor(
        session_id, "Visiting Sensei", _ADMIN.sub
    )


async def test_a_held_session_counts_its_members_and_visitors(db_client, as_admin):
    session = await _session(db_client, "2026-03-05")
    await _attend(db_client, session, await _member(db_client))
    await _attend(db_client, session, await _member(db_client))
    await _visitor(db_client, session)

    point = next(p for p in await _points() if p["session_id"] == session)

    assert point == {
        "session_id": session,
        "date": "2026-03-05",
        "members": 2,
        "visitors": 1,
    }


async def test_only_held_sessions_in_range_are_points_oldest_first(db_client, as_admin):
    later = await _session(db_client, "2026-03-20")
    earlier = await _session(db_client, "2026-03-02")
    cancelled = await _session(db_client, "2026-03-10")
    await SqlSessionInstanceRepository(db_client).cancel(cancelled)
    before_range = await _session(db_client, "2026-02-28")
    after_range = await _session(db_client, "2026-04-01")
    ours = {later, earlier, cancelled, before_range, after_range}

    points = [p for p in await _points() if p["session_id"] in ours]

    assert [p["session_id"] for p in points] == [earlier, later]
    assert points[0]["members"] == points[0]["visitors"] == 0


async def test_every_member_counts_whatever_their_status_today(db_client, as_admin):
    session = await _session(db_client, "2026-03-05")
    for status in ("active", "inactive", "suspended", "archived"):
        await _attend(db_client, session, await _member(db_client, status))

    point = next(p for p in await _points() if p["session_id"] == session)

    assert point["members"] == 4


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-03-31", "date_to": "2026-03-01"},
        {"date_from": "2025-01-01", "date_to": "2026-01-03"},
    ],
)
async def test_a_backwards_or_over_long_range_is_rejected(as_admin, params):
    assert (await _get(params)).status_code == 422


async def test_members_may_not_see_the_headcount(cookies_for):
    member = AccountClaims(sub=str(uuid.uuid4()), email="m@dojo.test", role="member")

    response = await _get(cookies=cookies_for(member))

    assert response.status_code == 403
