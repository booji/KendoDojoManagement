"""Reconciling a Session Template's Sessions leaves the past and Admin work alone (#578).

Extend Series and a recurrence change both reconcile a template's Sessions with
its recurrence. Served from PostgreSQL (db_client), because what is under test
includes Attendance, whose foreign key used to turn a reconcile into a 500.

Dates are relative to today: a template that started three weeks ago and runs
four weeks ahead, on Mondays.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.attendance.db_models import Attendance
from app.attendance.dependencies import get_attendance_repo
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.main import app
from app.members.dependencies import get_current_member_id
from app.sessions.repository import SqlSessionInstanceRepository

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")

_TODAY = date.today()
_THIS_MONDAY = _TODAY - timedelta(days=_TODAY.weekday())
_START = _THIS_MONDAY - timedelta(weeks=3)
_END = _THIS_MONDAY + timedelta(weeks=4)
_PAST_MONDAYS = [(_START + timedelta(weeks=n)).isoformat() for n in range(3)]
_NEXT_MONDAY = (_THIS_MONDAY + timedelta(weeks=1)).isoformat()


@pytest.fixture(autouse=True)
def admin():
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _ADMIN
    app.dependency_overrides.pop(get_attendance_repo, None)
    app.dependency_overrides.pop(get_current_member_id, None)
    yield
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api")


async def _series(c: AsyncClient) -> str:
    kind = await c.post("/session-types", json={"name": f"Keiko {uuid.uuid4().hex}"})
    assert kind.status_code == 201, kind.text
    segment = {"start_time": "19:00", "duration_minutes": 90}
    response = await c.post(
        "/sessions/templates",
        json={
            "title": "Weekly Keiko",
            "start_date": _START.isoformat(),
            "end_date": _END.isoformat(),
            "recurrence_days": [0],
            "interval_weeks": 1,
            "info": "Bring a bokken",
            "coach_notes": "Kihon focus",
            "segments": [{**segment, "type_ids": [kind.json()["id"]]}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _sessions(c: AsyncClient, template_id: str) -> dict[str, dict]:
    """The template's Sessions, keyed by date."""
    response = await c.get(
        "/sessions",
        params={
            "from": (_START - timedelta(weeks=1)).isoformat(),
            "to": (_END + timedelta(weeks=12)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return {s["date"]: s for s in response.json() if s["template_id"] == template_id}


async def _move(c: AsyncClient, session_id: str, day: str) -> None:
    response = await c.put(f"/sessions/{session_id}", json={"date": day})
    assert response.status_code == 200, response.text


async def _check_in(db, session_id: str) -> None:
    await db.execute(
        insert(Attendance).values(
            id=str(uuid.uuid4()),
            session_id=session_id,
            visitor_name="Hanako",
            checked_in_at=f"{_TODAY.isoformat()}T19:00:00+00:00",
            recorded_by=_ADMIN.sub,
        )
    )


async def _extend(c: AsyncClient, template_id: str) -> None:
    response = await c.post(
        f"/sessions/templates/{template_id}/extend",
        json={"end_date": (_END + timedelta(weeks=4)).isoformat()},
    )
    assert response.status_code == 200, response.text


def _day_after(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


async def test_extend_keeps_a_moved_session_that_has_attendance(db_client) -> None:
    """The issue's failure: a Monday moved to the Tuesday, checked in there,
    then Extend Series. That used to delete the Tuesday into the Attendance
    foreign key, a 500 on every attempt."""
    monday = _PAST_MONDAYS[1]
    tuesday = _day_after(monday)
    async with _client() as c:
        template_id = await _series(c)
        moved = (await _sessions(c, template_id))[monday]
        await _move(c, moved["id"], tuesday)
        await _check_in(db_client, moved["id"])

        await _extend(c, template_id)
        sessions = await _sessions(c, template_id)

    assert sessions[tuesday]["id"] == moved["id"]
    assert monday not in sessions, "the moved Monday must not come back"


async def test_extend_keeps_a_moved_future_session(db_client) -> None:
    """Without Attendance it used to be deleted silently, and the original
    date generated again. A moved Session keeps covering its original slot."""
    tuesday = _day_after(_NEXT_MONDAY)
    async with _client() as c:
        template_id = await _series(c)
        moved = (await _sessions(c, template_id))[_NEXT_MONDAY]
        await _move(c, moved["id"], tuesday)

        await _extend(c, template_id)
        sessions = await _sessions(c, template_id)

    assert sessions[tuesday]["id"] == moved["id"]
    assert _NEXT_MONDAY not in sessions, "the moved Monday must not come back"


async def test_a_recurrence_change_keeps_the_past_sessions(db_client) -> None:
    async with _client() as c:
        template_id = await _series(c)

        response = await c.patch(
            f"/sessions/templates/{template_id}", json={"recurrence_days": [2]}
        )
        assert response.status_code == 200, response.text
        sessions = await _sessions(c, template_id)

    for day in _PAST_MONDAYS:
        assert day in sessions, f"past Monday {day} was deleted"
        assert sessions[day]["coach_notes"] == "Kihon focus"
    assert _NEXT_MONDAY not in sessions, "a future Monday no longer covered stays"
    weekdays_from_today = {
        date.fromisoformat(d).weekday() for d in sessions if d >= _TODAY.isoformat()
    }
    assert weekdays_from_today == {2}
    assert not [
        d
        for d, s in sessions.items()
        if d < _TODAY.isoformat() and date.fromisoformat(d).weekday() == 2
    ], "the past is not backfilled with Wednesdays that never happened"


async def test_a_recurrence_change_keeps_a_future_session_an_admin_edited(
    db_client,
) -> None:
    async with _client() as c:
        template_id = await _series(c)
        edited = (await _sessions(c, template_id))[_NEXT_MONDAY]
        response = await c.put(
            f"/sessions/{edited['id']}", json={"info": "Grading prep"}
        )
        assert response.status_code == 200, response.text

        response = await c.patch(
            f"/sessions/templates/{template_id}", json={"recurrence_days": [2]}
        )
        assert response.status_code == 200, response.text
        sessions = await _sessions(c, template_id)

    assert sessions[_NEXT_MONDAY]["info"] == "Grading prep"


async def test_a_recurrence_change_keeps_a_future_session_with_attendance(
    db_client,
) -> None:
    async with _client() as c:
        template_id = await _series(c)
        attended = (await _sessions(c, template_id))[_NEXT_MONDAY]
        await _check_in(db_client, attended["id"])

        response = await c.patch(
            f"/sessions/templates/{template_id}", json={"recurrence_days": [2]}
        )
        assert response.status_code == 200, response.text
        sessions = await _sessions(c, template_id)

    assert sessions[_NEXT_MONDAY]["id"] == attended["id"]


async def test_a_cancelled_series_cannot_be_extended(db_client) -> None:
    """C6 of the audit: extend ignored is_active, generating live Sessions for
    a series the Admin had cancelled."""
    async with _client() as c:
        template_id = await _series(c)
        response = await c.delete(f"/sessions/templates/{template_id}")
        assert response.status_code == 200, response.text
        before = await _sessions(c, template_id)

        response = await c.post(
            f"/sessions/templates/{template_id}/extend",
            json={"end_date": (_END + timedelta(weeks=4)).isoformat()},
        )
        after = await _sessions(c, template_id)

    assert response.status_code == 422, response.text
    assert "cancelled" in response.json()["detail"]
    assert after == before


async def test_two_sessions_cannot_cover_one_slot_of_a_series(db_client) -> None:
    """C12 of the audit: only check-then-insert kept a slot single, which two
    concurrent extends can both pass. The database now refuses the second."""
    async with _client() as c:
        template_id = await _series(c)
    taken = {
        "title": "Weekly Keiko",
        "date": _day_after(_NEXT_MONDAY),
        "original_date": _NEXT_MONDAY,
        "template_id": template_id,
    }

    with pytest.raises(IntegrityError, match="uq_session_instances_template_slot"):
        await SqlSessionInstanceRepository(db_client).add(taken)
