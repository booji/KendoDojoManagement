"""Behaviour checks for the fakes themselves.

The conformance test next door proves the fakes match their interfaces in
shape. This proves the handful of behaviours the fakes actually implement --
envelope derivation, the upcoming/range filters, and the refusal to store a
column that does not exist -- so a fake that silently stops deriving is caught
here rather than as a puzzling failure in a migrated test file (#337).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.fake_repositories import (
    InMemoryAttendanceRepository,
    InMemorySessionInstanceRepository,
    InMemorySessionTypeRepository,
)


def _segment(start_time: str, duration_minutes: int) -> dict[str, object]:
    return {
        "start_time": start_time,
        "duration_minutes": duration_minutes,
        "type_ids": [],
    }


def test_envelope_is_derived_from_segments_not_supplied() -> None:
    repo = InMemorySessionInstanceRepository()
    record = repo.seed(segments=[_segment("19:00", 60), _segment("18:30", 45)])

    assert record["start_time"] == "18:30"
    assert record["end_time"] == "20:00"
    assert record["duration_minutes"] == 90


def test_envelope_runs_past_midnight_without_wrapping() -> None:
    # The case test_checkin_midnight_envelope.py used to seed as a raw
    # "25:00" string: derived here from a segment that crosses midnight.
    repo = InMemorySessionInstanceRepository()
    record = repo.seed(date="2026-03-01", segments=[_segment("23:30", 45)])

    assert record["end_time"] == "24:15"


def test_seeding_an_unknown_column_is_refused() -> None:
    repo = InMemorySessionInstanceRepository()

    with pytest.raises(TypeError, match="unknown column"):
        repo.seed(start_time="19:00")


async def test_list_upcoming_excludes_past_and_cancelled() -> None:
    today = date.today()
    repo = InMemorySessionInstanceRepository(
        [
            {"title": "yesterday", "date": (today - timedelta(days=1)).isoformat()},
            {"title": "today", "date": today.isoformat()},
            {
                "title": "cancelled",
                "date": (today + timedelta(days=1)).isoformat(),
                "cancelled": True,
            },
        ]
    )

    assert [r["title"] for r in await repo.list_upcoming()] == ["today"]


async def test_list_in_range_is_inclusive_of_both_bounds() -> None:
    repo = InMemorySessionInstanceRepository(
        [
            {"title": "before", "date": "2026-02-28"},
            {"title": "from", "date": "2026-03-01"},
            {"title": "to", "date": "2026-03-31"},
            {"title": "after", "date": "2026-04-01"},
        ]
    )

    rows = await repo.list_in_range(date(2026, 3, 1), date(2026, 3, 31))

    assert sorted(r["title"] for r in rows) == ["from", "to"]


async def test_cancel_future_for_template_leaves_past_instances_alone() -> None:
    repo = InMemorySessionInstanceRepository(
        [
            {"date": "2026-02-01", "template_id": "t1"},
            {"date": "2026-04-01", "template_id": "t1"},
            {"date": "2026-04-01", "template_id": "t2"},
        ]
    )

    cancelled = await repo.cancel_future_for_template("t1", date(2026, 3, 1))

    assert [r["date"] for r in cancelled] == ["2026-04-01"]
    assert [r["date"] for r in await repo.list() if r["cancelled"]] == ["2026-04-01"]


async def test_duplicate_session_type_name_is_refused() -> None:
    repo = InMemorySessionTypeRepository([{"name": "Kata"}])

    with pytest.raises(ValueError, match="already exists"):
        await repo.add("Kata")


async def test_attendance_display_name_comes_from_the_member_mapping() -> None:
    repo = InMemoryAttendanceRepository(display_names={"m1": "Ito Sensei"})
    await repo.check_in("s1", "m1", recorded_by="m1")
    await repo.check_in("s1", "m2", recorded_by="m2")

    rows = await repo.list_for_session("s1")

    assert [r["display_name"] for r in rows] == ["Ito Sensei", None]
