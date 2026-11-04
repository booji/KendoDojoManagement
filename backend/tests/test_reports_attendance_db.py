"""The attendance report, served from PostgreSQL (#559).

test_reports.py covers the router against a stub; the bugs in #559 lived in
the SQL repository, so these drive GET /reports/attendance (and its CSV) over
real rows. Attendance Rate is as GLOSSARY.md defines it: attended ÷ held
Sessions, counted from the later of the range start and the Member's join
date. A cancelled Session is not held, and is left out of the Sessions table.
"""

from __future__ import annotations

import csv
import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from app.attendance.db_models import Attendance
from app.attendance.dependencies import get_attendance_repo
from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.main import app
from app.members.dependencies import get_current_member_id
from app.members.repository import SqlMemberRepository
from app.sessions.repository import SqlSessionInstanceRepository

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")
_SEGMENT = {"start_time": "19:00", "duration_minutes": 90, "type_ids": []}
_RANGE = {"date_from": "2026-03-01", "date_to": "2026-03-31"}


@pytest.fixture(autouse=True)
def admin():
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN
    app.dependency_overrides.pop(get_attendance_repo, None)
    app.dependency_overrides.pop(get_current_member_id, None)
    yield
    app.dependency_overrides.clear()


async def _get(path: str, params: dict[str, str] = _RANGE):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(path, params=params)
    assert response.status_code == 200, response.text
    return response


async def _member(
    db, join_date: str = "2025-01-01", display_name: str | None = None
) -> str:
    member = await SqlMemberRepository(db).add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": "Ai",
            "surname": "Sato",
            "display_name": display_name,
            "join_date": join_date,
        }
    )
    return member["id"]


async def _session(db, date: str, cancelled: bool = False) -> str:
    repo = SqlSessionInstanceRepository(db)
    instance = await repo.add({"title": "Keiko", "date": date, "segments": [_SEGMENT]})
    if cancelled:
        await repo.cancel(instance["id"])
    return instance["id"]


async def _attend(db, session_id: str, member_id: str) -> None:
    await db.execute(
        insert(Attendance).values(
            id=str(uuid.uuid4()),
            session_id=session_id,
            member_id=member_id,
            checked_in_at="2026-03-01T19:00:00+00:00",
            recorded_by=_ADMIN.sub,
        )
    )


def _rate(body, member_id: str) -> dict:
    return next(r for r in body["member_rates"] if r["member_id"] == member_id)


async def test_member_rate_carries_the_member_name(db_client) -> None:
    named = await _member(db_client, display_name="Kenji")
    unnamed = await _member(db_client)
    session = await _session(db_client, "2026-03-05")
    await _attend(db_client, session, named)
    await _attend(db_client, session, unnamed)
    db_client.expire_all()

    body = (await _get("/reports/attendance")).json()

    assert _rate(body, named)["display_name"] == "Kenji"
    assert _rate(body, unnamed)["display_name"] == "Ai Sato"


async def test_cancelled_session_is_not_held(db_client) -> None:
    member = await _member(db_client)
    held = await _session(db_client, "2026-03-05")
    cancelled = await _session(db_client, "2026-03-12", cancelled=True)
    await _attend(db_client, held, member)
    await _attend(db_client, cancelled, member)
    await _session(db_client, "2026-03-19", cancelled=True)
    db_client.expire_all()

    body = (await _get("/reports/attendance")).json()

    assert [s["session_id"] for s in body["sessions"]] == [held]
    rate = _rate(body, member)
    assert (rate["sessions_attended"], rate["total_sessions"]) == (1, 1)
    assert rate["attendance_rate"] == 1.0


async def test_rate_counts_from_the_later_of_range_start_and_join_date(
    db_client,
) -> None:
    joined_mid_month = await _member(db_client, join_date="2026-03-10")
    joined_before = await _member(db_client, join_date="2025-01-01")
    before_joining = await _session(db_client, "2026-03-05")
    on_join_day = await _session(db_client, "2026-03-10")
    await _session(db_client, "2026-03-17")
    await _attend(db_client, before_joining, joined_before)
    # A trial Session before the join date counts on neither side.
    await _attend(db_client, before_joining, joined_mid_month)
    await _attend(db_client, on_join_day, joined_mid_month)
    await _attend(db_client, on_join_day, joined_before)
    db_client.expire_all()

    body = (await _get("/reports/attendance")).json()

    late = _rate(body, joined_mid_month)
    assert (late["sessions_attended"], late["total_sessions"]) == (1, 2)
    assert late["attendance_rate"] == 0.5
    early = _rate(body, joined_before)
    assert (early["sessions_attended"], early["total_sessions"]) == (2, 3)
    assert early["attendance_rate"] == 0.6667


async def test_csv_leaves_out_cancelled_sessions(db_client) -> None:
    held = await _session(db_client, "2026-03-05")
    await _session(db_client, "2026-03-12", cancelled=True)
    db_client.expire_all()

    response = await _get("/reports/attendance/csv")

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [(r["session_id"], r["date"]) for r in rows] == [(held, "2026-03-05")]
