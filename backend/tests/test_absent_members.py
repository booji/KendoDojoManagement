"""Absent Members on the Charts tab (#564).

An Absent Member (GLOSSARY.md) has no Attendance in the last 14 days, counting
one who joined more than 14 days ago and has never attended. Only held
Sessions count. Served from PostgreSQL through GET /reports/absent-members,
as of today.

Other tests leave Members in the shared database, so each test looks only at
the Members it seeds.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from app.attendance.db_models import Attendance
from app.auth.guards import REQUIRE_ADMIN
from app.auth.schemas import AccountClaims
from app.main import app
from app.members.repository import SqlMemberRepository
from app.sessions.repository import SqlSessionInstanceRepository

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")
_SEGMENT = {"start_time": "19:00", "duration_minutes": 90, "type_ids": []}


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def as_admin(db_client):
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN


async def _get(path: str, **kwargs):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        return await c.get(path, **kwargs)


async def _member(db, joined_days_ago: int = 365, status: str = "active") -> str:
    member = await SqlMemberRepository(db).add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": "Ai",
            "surname": "Sato",
            "join_date": _ago(joined_days_ago),
            "membership_status": status,
        }
    )
    return member["id"]


async def _attend(db, member_id: str, days_ago: int, cancelled: bool = False):
    repo = SqlSessionInstanceRepository(db)
    session = await repo.add(
        {"title": "Keiko", "date": _ago(days_ago), "segments": [_SEGMENT]}
    )
    if cancelled:
        await repo.cancel(session["id"])
    await db.execute(
        insert(Attendance).values(
            id=str(uuid.uuid4()),
            session_id=session["id"],
            member_id=member_id,
            checked_in_at=f"{_ago(days_ago)}T19:00:00+00:00",
            recorded_by=_ADMIN.sub,
        )
    )


async def _absent(params: str = "") -> dict[str, dict]:
    response = await _get(f"/reports/absent-members{params}")
    assert response.status_code == 200, response.text
    return {row["member_id"]: row for row in response.json()}


async def test_a_member_last_seen_20_days_ago_is_absent(db_client, as_admin):
    member = await _member(db_client)
    await _attend(db_client, member, 40)
    await _attend(db_client, member, 20)
    db_client.expire_all()

    row = (await _absent())[member]

    assert row["display_name"] == "Ai Sato"
    assert row["email"].endswith("@dojo.test")
    assert row["last_attended"] == _ago(20)
    assert row["days_absent"] == 20


async def test_attendance_14_days_ago_is_within_the_last_14_days(db_client, as_admin):
    seen_14_days_ago = await _member(db_client)
    await _attend(db_client, seen_14_days_ago, 14)
    seen_15_days_ago = await _member(db_client)
    await _attend(db_client, seen_15_days_ago, 15)
    db_client.expire_all()

    absent = await _absent()

    assert seen_14_days_ago not in absent
    assert absent[seen_15_days_ago]["days_absent"] == 15


async def test_a_member_who_joined_over_14_days_ago_and_never_attended_is_absent(
    db_client, as_admin
):
    never = await _member(db_client, joined_days_ago=30)
    new = await _member(db_client, joined_days_ago=14)
    db_client.expire_all()

    absent = await _absent()

    assert new not in absent
    assert absent[never]["last_attended"] is None
    assert absent[never]["days_absent"] == 30


async def test_attendance_at_a_cancelled_session_does_not_count(db_client, as_admin):
    member = await _member(db_client)
    await _attend(db_client, member, 20)
    await _attend(db_client, member, 3, cancelled=True)
    db_client.expire_all()

    assert (await _absent())[member]["last_attended"] == _ago(20)


async def test_attendance_at_a_future_session_does_not_end_an_absence(
    db_client, as_admin
):
    member = await _member(db_client)
    await _attend(db_client, member, 20)
    await _attend(db_client, member, -3)
    db_client.expire_all()

    assert (await _absent())[member]["last_attended"] == _ago(20)


async def test_the_longest_absent_come_first(db_client, as_admin):
    # Further back than anyone else's absence, so these lead the list.
    a_while = await _member(db_client, joined_days_ago=5000)
    await _attend(db_client, a_while, 4000)
    longest = await _member(db_client, joined_days_ago=4500)
    db_client.expire_all()

    rows = list(await _absent())

    assert rows[:2] == [longest, a_while]


async def test_only_active_members_are_listed_by_default(db_client, as_admin):
    active = await _member(db_client, status="active")
    inactive = await _member(db_client, status="inactive")
    db_client.expire_all()

    absent = await _absent()

    assert active in absent
    assert inactive not in absent


async def test_the_status_filter_chooses_who_is_listed(db_client, as_admin):
    by_status = {
        s: await _member(db_client, status=s)
        for s in ("active", "inactive", "suspended", "archived")
    }
    db_client.expire_all()

    absent = await _absent("?status=inactive&status=archived")

    assert {s for s, m in by_status.items() if m in absent} == {
        "inactive",
        "archived",
    }


async def test_an_unknown_status_is_rejected(db_client, as_admin):
    response = await _get("/reports/absent-members?status=visitor")

    assert response.status_code == 422


async def test_members_may_not_see_absent_members(cookies_for):
    member = AccountClaims(sub=str(uuid.uuid4()), email="m@dojo.test", role="member")

    response = await _get("/reports/absent-members", cookies=cookies_for(member))

    assert response.status_code == 403


async def test_absent_members_need_a_signed_in_admin():
    response = await _get("/reports/absent-members")

    assert response.status_code == 401
