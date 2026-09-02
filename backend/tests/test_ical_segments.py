"""
Tests for issue #174 — iCal output for multi-segment sessions (parent PRD #172).

A session may now have multiple segments, each with its own start_time,
duration_minutes, optional coach_notes, and ordered type_ids. The iCal feed
must still produce exactly ONE VEVENT per session:
  - SUMMARY = session title
  - DTSTART/DTEND = the derived envelope (min start -> max end across segments)
  - DESCRIPTION = a per-segment breakdown ("HH:MM-HH:MM Type, Type" per
    segment, newline-joined) followed by the session's public `info` field
  - coach_notes (session-level AND per-segment) and notes must NEVER appear
    in the output

These tests exercise `app.sessions.ical.build_ical` directly with
segment-shaped session dicts. build_ical does not yet understand segments,
so these tests are expected to fail until it is updated.
"""

from __future__ import annotations

from app.sessions.ical import build_ical


def _segmented_session(**overrides):
    base = {
        "id": "uid-multiseg",
        "title": "Saturday Training Block",
        "date": "2099-11-07",
        "location": "Main Dojo",
        "info": "Bring your bogu",
        "cancelled": False,
        "notes": "Internal scheduling note",
        "segments": [
            {
                "start_time": "09:00",
                "duration_minutes": 60,
                "coach_notes": "SECRET: focus on footwork",
                "type_names": ["Kihon"],
            },
            {
                "start_time": "10:00",
                "duration_minutes": 45,
                "coach_notes": "SECRET: sparring pairs TBD",
                "type_names": ["Jigeki", "Kata Practice"],
            },
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# One VEVENT per session, even with multiple segments
# ---------------------------------------------------------------------------


def test_multi_segment_session_produces_exactly_one_vevent() -> None:
    """A session with multiple segments must still yield exactly one
    BEGIN:VEVENT/END:VEVENT block."""
    sessions = [_segmented_session()]
    result = build_ical(sessions)
    assert result.count("BEGIN:VEVENT") == 1
    assert result.count("END:VEVENT") == 1


def test_multiple_sessions_each_with_segments_produce_one_vevent_each() -> None:
    """Two distinct multi-segment sessions must produce two VEVENTs total —
    not one per segment."""
    sessions = [
        _segmented_session(id="uid-a", title="Session A"),
        _segmented_session(id="uid-b", title="Session B"),
    ]
    result = build_ical(sessions)
    assert result.count("BEGIN:VEVENT") == 2
    assert "SUMMARY:Session A" in result
    assert "SUMMARY:Session B" in result


# ---------------------------------------------------------------------------
# DTSTART / DTEND derived from the envelope across all segments
# ---------------------------------------------------------------------------


def test_dtstart_dtend_use_derived_envelope_across_segments() -> None:
    """DTSTART must be the earliest segment start (09:00) and DTEND the
    latest segment end (10:45 = 10:00 + 45min), not any single segment's
    own start/end."""
    sessions = [_segmented_session()]
    result = build_ical(sessions)
    assert "DTSTART:20991107T090000" in result
    assert "DTEND:20991107T104500" in result


def test_dtstart_dtend_for_overlapping_segments() -> None:
    """Overlapping segments must still produce a correct min-start/max-end
    envelope for DTSTART/DTEND."""
    sessions = [
        _segmented_session(
            segments=[
                {
                    "start_time": "19:00",
                    "duration_minutes": 90,
                    "type_names": ["General Training"],
                },
                {
                    "start_time": "19:30",
                    "duration_minutes": 15,
                    "type_names": ["Kata Practice"],
                },
            ]
        )
    ]
    result = build_ical(sessions)
    assert "DTSTART:20991107T190000" in result
    assert "DTEND:20991107T203000" in result


def test_dtend_at_midnight_does_not_crash() -> None:
    """A segment running to midnight yields an envelope end of "24:00";
    DTEND must roll into 00:00 the next day rather than raise on hour=24."""
    sessions = [
        _segmented_session(
            date="2099-11-07",
            segments=[
                {
                    "start_time": "22:00",
                    "duration_minutes": 120,
                    "type_names": ["General Training"],
                }
            ],
        )
    ]
    result = build_ical(sessions)
    assert "DTSTART:20991107T220000" in result
    assert "DTEND:20991108T000000" in result


# ---------------------------------------------------------------------------
# DESCRIPTION: per-segment breakdown, then info
# ---------------------------------------------------------------------------


def test_description_contains_per_segment_breakdown_then_info() -> None:
    """DESCRIPTION must list each segment's time range and comma-joined
    type names, followed by the session's public info text."""
    sessions = [_segmented_session()]
    result = build_ical(sessions)
    description_line = next(
        line for line in result.split("\r\n") if line.startswith("DESCRIPTION:")
    )
    assert "09:00" in description_line
    assert "10:00" in description_line
    assert "Kihon" in description_line
    assert "Jigeki" in description_line
    assert "Kata Practice" in description_line
    assert "Bring your bogu" in description_line


def test_description_segment_breakdown_uses_time_range_and_comma_joined_types() -> None:
    """Each segment line in the breakdown must read 'HH:MM-HH:MM Type, Type'."""
    sessions = [
        _segmented_session(
            segments=[
                {
                    "start_time": "09:00",
                    "duration_minutes": 60,
                    "type_names": ["Jigeki", "Kata Practice"],
                }
            ],
            info=None,
        )
    ]
    result = build_ical(sessions)
    description_line = next(
        line for line in result.split("\r\n") if line.startswith("DESCRIPTION:")
    )
    assert "09:00" in description_line and "10:00" in description_line
    # RFC 5545 escapes the comma in the joined type list to "\,"; clients
    # unescape it for display.
    assert "Jigeki\\, Kata Practice" in description_line


# ---------------------------------------------------------------------------
# Private fields must NEVER appear
# ---------------------------------------------------------------------------


def test_session_level_coach_notes_never_appears() -> None:
    sessions = [_segmented_session(coach_notes="SECRET session-level note")]
    result = build_ical(sessions)
    assert "SECRET session-level note" not in result
    assert "coach_notes" not in result.lower()


def test_segment_level_coach_notes_never_appears() -> None:
    """Per-segment coach_notes must never leak into the iCal output."""
    sessions = [_segmented_session()]
    result = build_ical(sessions)
    assert "SECRET: focus on footwork" not in result
    assert "SECRET: sparring pairs TBD" not in result


def test_notes_field_never_appears() -> None:
    sessions = [_segmented_session()]
    result = build_ical(sessions)
    assert "Internal scheduling note" not in result
