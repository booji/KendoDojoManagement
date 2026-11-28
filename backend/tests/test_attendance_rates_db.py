"""Top 10 Attendance Rates over the Charts tab's range, from PostgreSQL (#562).

Attendance Rate is as GLOSSARY.md defines it (test_reports_attendance_db.py
covers the counting from #559). These cover what the chart ranks: Members of
the chosen Membership Statuses with at least 4 eligible held Sessions in the
range, Visitors never, the 10 highest.

Everything runs over March 2017, a month no other test seeds, so Sessions
other tests leave behind cannot change these rates. The HTTP tests cover
GET /reports/attendance-rates' wiring and guards.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from app.attendance.db_models import Attendance
from app.auth.guards import REQUIRE_ADMIN
from app.auth.schemas import AccountClaims
from app.main import app
from app.members.repository import SqlMemberRepository
from app.reports.repository import SqlReportRepository
from app.sessions.repository import SqlSessionInstanceRepository

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")
_SEGMENT = {"start_time": "19:00", "duration_minutes": 90, "type_ids": []}
_FROM, _TO = "2017-03-01", "2017-03-31"
# The Thursdays of March 2017.
_THURSDAYS = ["2017-03-02", "2017-03-09", "2017-03-16", "2017-03-23", "2017-03-30"]


async def _member(
    db,
    first_name: str = "Ai",
    display_name: str | None = None,
    membership_status: str = "active",
    join_date: str = "2016-01-01",
) -> str:
    member = await SqlMemberRepository(db).add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": first_name,
            "surname": "Sato",
            "display_name": display_name,
            "join_date": join_date,
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
            checked_in_at="2017-03-01T19:00:00+00:00",
            recorded_by=_ADMIN.sub,
        )
    )


async def _top(db, statuses=("active",)) -> list[dict]:
    db.expire_all()
    return await SqlReportRepository(db).top_attendance_rates(
        _FROM, _TO, list(statuses)
    )


async def test_a_member_s_rate_carries_their_name_and_counts(db_client) -> None:
    kenji = await _member(db_client, display_name="Kenji")
    sessions = [await _session(db_client, day) for day in _THURSDAYS[:4]]
    for session in sessions[:3]:
        await _attend(db_client, session, kenji)

    assert await _top(db_client) == [
        {
            "member_id": kenji,
            "display_name": "Kenji",
            "sessions_attended": 3,
            "total_sessions": 4,
            "attendance_rate": 0.75,
        }
    ]


async def test_a_member_with_fewer_than_4_eligible_held_sessions_is_not_ranked(
    db_client,
) -> None:
    sessions = [await _session(db_client, day) for day in _THURSDAYS]
    # Not held, so it does not make up the fourth.
    await _session(db_client, "2017-03-12", cancelled=True)
    # Joined after the first two Thursdays: three eligible held Sessions.
    newcomer = await _member(db_client, join_date="2017-03-10")
    for session in sessions[2:]:
        await _attend(db_client, session, newcomer)
    # Joined just in time for the fourth from last: four, all attended.
    regular = await _member(db_client, join_date="2017-03-09")
    for session in sessions[1:]:
        await _attend(db_client, session, regular)

    assert [r["member_id"] for r in await _top(db_client)] == [regular]


async def test_only_members_of_the_chosen_statuses_are_ranked(db_client) -> None:
    sessions = [await _session(db_client, day) for day in _THURSDAYS[:4]]
    by_status = {
        status: await _member(db_client, membership_status=status)
        for status in ("active", "inactive", "suspended", "archived")
    }
    for member in by_status.values():
        await _attend(db_client, sessions[0], member)

    ranked = await _top(db_client, ("inactive", "archived"))

    assert {r["member_id"] for r in ranked} == {
        by_status["inactive"],
        by_status["archived"],
    }


async def test_visitors_are_never_ranked(db_client) -> None:
    for day in _THURSDAYS:
        await _attend(db_client, await _session(db_client, day), None, "Guest")

    assert await _top(db_client) == []


async def test_the_ten_highest_rates_come_highest_first(db_client) -> None:
    sessions = [await _session(db_client, day) for day in _THURSDAYS]
    # Of five held Sessions: one Member attends none, the others 1 to 5.
    attended = {"Ren": 0, "Mio": 1, "Sho": 2, "Kai": 3, "Rio": 4, "Yui": 5}
    for name, count in attended.items():
        member = await _member(db_client, first_name=name)
        for session in sessions[:count]:
            await _attend(db_client, session, member)
    # 4 of 4: the same 100% as Yui, over fewer Sessions, so ranked below her.
    late = await _member(db_client, first_name="Aya", join_date="2017-03-05")
    for session in sessions[1:]:
        await _attend(db_client, session, late)
    # Never attended: 0%, tied with Ren, then by name.
    for i in range(4):
        await _member(db_client, first_name=f"Z{i}")

    ranked = await _top(db_client)

    assert [(r["display_name"], r["attendance_rate"]) for r in ranked] == [
        ("Yui Sato", 1.0),
        ("Aya Sato", 1.0),
        ("Rio Sato", 0.8),
        ("Kai Sato", 0.6),
        ("Sho Sato", 0.4),
        ("Mio Sato", 0.2),
        ("Ren Sato", 0.0),
        ("Z0 Sato", 0.0),
        ("Z1 Sato", 0.0),
        ("Z2 Sato", 0.0),
    ]


# --- GET /reports/attendance-rates ------------------------------------------

_PATH = "/reports/attendance-rates"


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def as_admin(db_client):
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN


async def _get(params=(), **kwargs):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        return await c.get(_PATH, params=params, **kwargs)


async def test_admin_gets_the_top_rates_over_the_range_for_the_ticked_statuses(
    db_client, as_admin
) -> None:
    sessions = [await _session(db_client, day) for day in _THURSDAYS[:4]]
    member = await _member(db_client, membership_status="suspended")
    await _attend(db_client, sessions[0], member)
    db_client.expire_all()
    in_range = [("date_from", _FROM), ("date_to", _TO)]

    by_default = await _get(in_range)
    suspended = await _get([*in_range, ("status", "suspended")])

    assert by_default.status_code == 200, by_default.text
    assert by_default.json() == []
    assert suspended.status_code == 200, suspended.text
    assert [(r["member_id"], r["attendance_rate"]) for r in suspended.json()] == [
        (member, 0.25)
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2017-03-31", "date_to": "2017-03-01"},
        {"date_from": "2016-01-01", "date_to": "2017-03-31"},
        {"date_from": _FROM, "date_to": _TO, "status": "visitor"},
        {"date_to": _TO},
    ],
    ids=["reversed", "over 366 days", "unknown status", "no start"],
)
async def test_a_bad_query_is_rejected(db_client, as_admin, params) -> None:
    assert (await _get(params)).status_code == 422


async def test_members_may_not_see_attendance_rates(cookies_for) -> None:
    member = AccountClaims(sub=str(uuid.uuid4()), email="m@dojo.test", role="member")

    response = await _get(
        {"date_from": _FROM, "date_to": _TO}, cookies=cookies_for(member)
    )

    assert response.status_code == 403


async def test_attendance_rates_need_a_signed_in_admin() -> None:
    response = await _get({"date_from": _FROM, "date_to": _TO})

    assert response.status_code == 401
