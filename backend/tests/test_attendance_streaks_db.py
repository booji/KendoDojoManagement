"""Top 10 Attendance Streaks this year, served from PostgreSQL (#563).

test_attendance_streak.py covers the week walk itself. These cover what the
repository feeds it and what it returns: held Sessions only, Members of the
chosen Membership Statuses only, Visitors never, the 10 longest.

The repository is driven with a fixed ``today`` in 2019, a year no other test
seeds, so Sessions other tests leave behind cannot break these streaks.
GET /reports/streaks passes the real today; the HTTP tests cover only that
wiring and the guards.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from app.attendance.db_models import Attendance
from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.main import app
from app.members.repository import SqlMemberRepository
from app.reports.repository import SqlReportRepository
from app.sessions.repository import SqlSessionInstanceRepository

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")
_SEGMENT = {"start_time": "19:00", "duration_minutes": 90, "type_ids": []}
# Thursdays of consecutive weeks in March 2019.
_WEEKS = ["2019-03-07", "2019-03-14", "2019-03-21", "2019-03-28"]
_TODAY = date(2019, 3, 31)


async def _member(
    db,
    first_name: str = "Ai",
    display_name: str | None = None,
    membership_status: str = "active",
) -> str:
    member = await SqlMemberRepository(db).add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": first_name,
            "surname": "Sato",
            "display_name": display_name,
            "join_date": "2018-01-01",
            "membership_status": membership_status,
        }
    )
    return member["id"]


async def _session(db, day: str, cancelled: bool = False) -> str:
    repo = SqlSessionInstanceRepository(db)
    instance = await repo.add({"title": "Keiko", "date": day, "segments": [_SEGMENT]})
    if cancelled:
        await repo.cancel(instance["id"])
    return instance["id"]


async def _attend(
    db, session_id: str, member_id: str | None, visitor_name: str | None = None
) -> None:
    await db.execute(
        insert(Attendance).values(
            id=str(uuid.uuid4()),
            session_id=session_id,
            member_id=member_id,
            visitor_name=visitor_name,
            checked_in_at="2019-03-01T19:00:00+00:00",
            recorded_by=_ADMIN.sub,
        )
    )


async def _streaks(db, statuses=("active",), today: date = _TODAY) -> list[dict]:
    db.expire_all()
    return await SqlReportRepository(db).attendance_streaks(list(statuses), today)


async def test_a_member_s_streak_carries_their_name_and_weeks(db_client) -> None:
    kenji = await _member(db_client, display_name="Kenji")
    for day in _WEEKS:
        await _attend(db_client, await _session(db_client, day), kenji)

    assert await _streaks(db_client) == [
        {"member_id": kenji, "display_name": "Kenji", "weeks": 4, "running": True}
    ]


async def test_a_cancelled_session_neither_breaks_nor_extends_a_streak(
    db_client,
) -> None:
    member = await _member(db_client)
    await _attend(db_client, await _session(db_client, _WEEKS[0]), member)
    await _session(db_client, _WEEKS[1], cancelled=True)
    await _attend(db_client, await _session(db_client, _WEEKS[2]), member)
    # Attending a cancelled Session does not make it held.
    await _attend(db_client, await _session(db_client, _WEEKS[3], True), member)

    [streak] = await _streaks(db_client)
    assert (streak["display_name"], streak["weeks"]) == ("Ai Sato", 2)


async def test_only_members_of_the_chosen_statuses_are_ranked(db_client) -> None:
    session = await _session(db_client, _WEEKS[0])
    by_status = {
        status: await _member(db_client, membership_status=status)
        for status in ("active", "inactive", "suspended", "archived")
    }
    for member in by_status.values():
        await _attend(db_client, session, member)

    ranked = await _streaks(db_client, ("inactive", "archived"))

    assert {s["member_id"] for s in ranked} == {
        by_status["inactive"],
        by_status["archived"],
    }


async def test_visitors_are_never_ranked(db_client) -> None:
    for day in _WEEKS:
        await _attend(db_client, await _session(db_client, day), None, "Guest")

    assert await _streaks(db_client) == []


async def test_the_ten_longest_streaks_come_longest_first(db_client) -> None:
    sessions = [await _session(db_client, day) for day in _WEEKS]
    # Twelve Members: two attend all four weeks, ten attend only the last.
    four_weeks = [await _member(db_client, first_name=n) for n in ("Bo", "Al")]
    one_week = [await _member(db_client, first_name=f"M{i:02}") for i in range(10)]
    for member in four_weeks:
        for session in sessions:
            await _attend(db_client, session, member)
    for member in one_week:
        await _attend(db_client, sessions[-1], member)

    ranked = await _streaks(db_client)

    assert [(s["display_name"], s["weeks"]) for s in ranked] == [
        ("Al Sato", 4),
        ("Bo Sato", 4),
        *[(f"M{i:02} Sato", 1) for i in range(8)],
    ]


async def test_attendance_outside_the_year_to_date_is_not_ranked(
    db_client,
) -> None:
    member = await _member(db_client)
    await _attend(db_client, await _session(db_client, "2018-12-27"), member)
    await _attend(db_client, await _session(db_client, "2019-04-04"), member)

    assert await _streaks(db_client) == []


# --- GET /reports/streaks ---------------------------------------------------


@pytest.fixture
def as_admin(db_client):
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN
    yield
    app.dependency_overrides.pop(REQUIRE_ADMIN, None)


async def _get(path: str, **kwargs):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        return await c.get(path, **kwargs)


async def test_admin_gets_streaks_up_to_today_for_the_ticked_statuses(
    db_client, as_admin
) -> None:
    # Suspended, so Members other tests leave behind are unlikely to crowd it
    # out of the top 10.
    member = await _member(db_client, membership_status="suspended")
    today = await _session(db_client, date.today().isoformat())
    await _attend(db_client, today, member)
    db_client.expire_all()

    by_default = await _get("/reports/streaks")
    suspended = await _get("/reports/streaks?status=suspended")

    assert by_default.status_code == 200, by_default.text
    assert member not in {s["member_id"] for s in by_default.json()}
    assert suspended.status_code == 200, suspended.text
    [streak] = [s for s in suspended.json() if s["member_id"] == member]
    assert (streak["weeks"], streak["running"]) == (1, True)


async def test_an_unknown_status_is_rejected(db_client, as_admin) -> None:
    response = await _get("/reports/streaks?status=active&status=visitor")

    assert response.status_code == 422


async def test_members_may_not_see_streaks(cookies_for) -> None:
    member = AccountClaims(sub=str(uuid.uuid4()), email="m@dojo.test", role="member")

    response = await _get("/reports/streaks", cookies=cookies_for(member))

    assert response.status_code == 403


async def test_streaks_need_a_signed_in_admin() -> None:
    assert (await _get("/reports/streaks")).status_code == 401
