"""Real date/time columns (#433) leave the API's ISO strings unchanged.

Runs against PostgreSQL (db_session): the repositories' dicts are what the
routers serialise, so a value read back from a date/time/timestamptz column
must be the same string the app wrote — 'YYYY-MM-DD', 'HH:MM' (Postgres
itself would say 'HH:MM:SS'), and ISO-8601 with its offset.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.attendance.repository import SqlAttendanceRepository
from app.grades.repository import SqlGradeRepository
from app.members.repository import SqlMemberRepository
from app.sessions.repository import (
    SqlSessionInstanceRepository,
    SqlSessionTemplateRepository,
)

_SEGMENT = {"start_time": "07:30", "duration_minutes": 90, "type_ids": []}


async def test_values_read_back_as_the_strings_the_app_wrote(db_session) -> None:
    members = SqlMemberRepository(db_session)
    member = await members.add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": "Ai",
            "surname": "Sato",
            "dob": date(2010, 2, 28),
            "join_date": date(2026, 1, 1),
        }
    )
    template = await SqlSessionTemplateRepository(db_session).add(
        {
            "title": "Keiko",
            "start_date": "2026-09-01",
            "end_date": "2027-03-01",
            "recurrence": "weekly",
            "segments": [_SEGMENT],
        }
    )
    instances = SqlSessionInstanceRepository(db_session)
    session = await instances.add(
        {"title": "Keiko", "date": "2026-10-01", "segments": [_SEGMENT]}
    )
    attended = await SqlAttendanceRepository(db_session).check_in(
        session["id"], member["id"], str(uuid.uuid4())
    )
    grades = SqlGradeRepository(db_session)
    await grades.add_promotion(
        member["id"], "SHODAN", "Shodan", None, "2026-01-15T00:00:00+00:00"
    )
    # Read from the database, not the objects still in the identity map.
    db_session.expire_all()

    member = await members.get(member["id"])
    assert (member["dob"], member["join_date"]) == ("2010-02-28", "2026-01-01")

    template = await SqlSessionTemplateRepository(db_session).get(template["id"])
    assert (template["start_date"], template["end_date"]) == (
        "2026-09-01",
        "2027-03-01",
    )
    assert template["segments"][0]["start_time"] == "07:30"

    [session] = await instances.list_in_range(date(2026, 10, 1), date(2026, 10, 1))
    assert session["date"] == "2026-10-01"
    assert session["scheduled_at"] == "2026-10-01T07:30:00"
    assert session["segments"][0]["start_time"] == "07:30"

    [checked_in] = await SqlAttendanceRepository(db_session).list_for_session(
        session["id"]
    )
    assert checked_in["checked_in_at"] == attended["checked_in_at"]

    [promotion] = await grades.get_history(member["id"])
    assert promotion["promoted_at"] == "2026-01-15T00:00:00+00:00"


@contextmanager
def _sent_parameters():
    """Every parameter the driver is handed, across all statements."""
    sent: list = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        sent.extend(parameters if isinstance(parameters, list | tuple) else [])

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        yield sent
    finally:
        event.remove(Engine, "before_cursor_execute", capture)


async def test_calendar_range_compares_dates_not_strings(db_session) -> None:
    """#449: with well-formed ISO data a string comparison returns the same
    rows, so only what reaches Postgres shows the difference. The range
    bounds must arrive as dates, compared against a `date` column, never as
    text compared lexically."""
    instances = SqlSessionInstanceRepository(db_session)

    with _sent_parameters() as sent:
        await instances.list_in_range(date(2026, 10, 1), date(2026, 10, 31))

    assert date(2026, 10, 1) in sent
    assert date(2026, 10, 31) in sent
    assert not any(isinstance(p, str) and p.startswith("2026-10-") for p in sent)
