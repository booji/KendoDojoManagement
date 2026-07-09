"""Issue #202 — timezone-aware iCal events (TZID + VTIMEZONE).

The feed must stop emitting floating time. When a dojo timezone is supplied,
each event's DTSTART/DTEND carry a TZID parameter and the calendar includes a
matching VTIMEZONE component whose STANDARD/DAYLIGHT observances encode the
correct DST offsets — so an event stored as 19:00 dojo-local resolves to the
right absolute instant in every client, across summer-time boundaries.

Pure-function tests only (no DB, no HTTP).
"""

from __future__ import annotations

from app.sessions.ical import build_ical


def _session(session_id: str, date: str, start_time: str, duration: int = 90):
    return {
        "id": session_id,
        "title": "Keiko",
        "date": date,
        "segments": [
            {
                "start_time": start_time,
                "duration_minutes": duration,
                "type_names": ["General"],
            }
        ],
        "location": None,
        "info": None,
        "cancelled": False,
    }


def _description(result: str) -> str:
    return next(
        line for line in result.split("\r\n") if line.startswith("DESCRIPTION:")
    )


def test_no_tz_name_keeps_floating_time() -> None:
    """Backward-compatible: without a zone, DTSTART stays floating (no TZID)."""
    result = build_ical([_session("uid", "2099-06-02", "19:00")])
    assert "DTSTART:20990602T190000" in result
    assert "TZID" not in result
    assert "VTIMEZONE" not in result


def test_summer_event_carries_tzid_and_local_walltime() -> None:
    """A June (BST) London event keeps its 19:00 local wall time, tagged TZID."""
    result = build_ical(
        [_session("uid", "2099-06-02", "19:00")], tz_name="Europe/London"
    )
    assert "DTSTART;TZID=Europe/London:20990602T190000" in result
    assert "DTEND;TZID=Europe/London:20990602T203000" in result


def test_includes_vtimezone_with_matching_tzid() -> None:
    """A VTIMEZONE component defining the referenced TZID must be present."""
    result = build_ical(
        [_session("uid", "2099-06-02", "19:00")], tz_name="Europe/London"
    )
    assert "BEGIN:VTIMEZONE" in result
    assert "TZID:Europe/London" in result
    assert "END:VTIMEZONE" in result
    # VTIMEZONE must appear before the first event that references it.
    assert result.index("BEGIN:VTIMEZONE") < result.index("BEGIN:VEVENT")


def test_summer_observance_has_bst_offset() -> None:
    """June falls in British Summer Time — DAYLIGHT observance TZOFFSETTO:+0100."""
    result = build_ical(
        [_session("uid", "2099-06-02", "19:00")], tz_name="Europe/London"
    )
    assert "BEGIN:DAYLIGHT" in result
    assert "TZOFFSETFROM:+0000" in result
    assert "TZOFFSETTO:+0100" in result


def test_winter_observance_has_gmt_offset() -> None:
    """A January (GMT) London event resolves to a STANDARD +0000 observance."""
    result = build_ical(
        [_session("uid", "2099-01-15", "19:00")], tz_name="Europe/London"
    )
    assert "BEGIN:STANDARD" in result
    assert "TZOFFSETTO:+0000" in result


def test_feed_spanning_dst_boundary_emits_both_observances() -> None:
    """Upcoming sessions either side of the autumn clock change must each get
    the right offset, so the VTIMEZONE carries both a DAYLIGHT and a STANDARD
    observance covering the span."""
    result = build_ical(
        [
            _session("uid-bst", "2099-10-01", "19:00"),  # BST, +0100
            _session("uid-gmt", "2099-11-01", "19:00"),  # GMT, +0000
        ],
        tz_name="Europe/London",
    )
    assert "BEGIN:DAYLIGHT" in result
    assert "BEGIN:STANDARD" in result
    # Both events keep their literal local wall time.
    assert "DTSTART;TZID=Europe/London:20991001T190000" in result
    assert "DTSTART;TZID=Europe/London:20991101T190000" in result


def test_fixed_offset_zone_emits_single_standard() -> None:
    """A zone without DST (UTC) still defines its TZID via one STANDARD block."""
    result = build_ical([_session("uid", "2099-06-02", "19:00")], tz_name="UTC")
    assert "TZID:UTC" in result
    assert "BEGIN:STANDARD" in result
    assert "TZOFFSETTO:+0000" in result
    assert "BEGIN:DAYLIGHT" not in result
