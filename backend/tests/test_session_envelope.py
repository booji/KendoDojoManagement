"""
Unit tests for issue #174 — pure time-envelope derivation for session segments.

A session's displayed time is DERIVED from its segments on read:
  envelope_start = min(segment.start_time for segment in segments)
  envelope_end   = max(segment.start_time + segment.duration_minutes for segment in segments)

This module does not exist yet (app/sessions/envelope.py) — these tests are
expected to fail on ImportError until it is implemented.
"""

from __future__ import annotations


def test_single_segment_envelope_is_its_own_start_and_end() -> None:
    """A session with exactly one segment has an envelope equal to that
    segment's own start time and start+duration end time."""
    from app.sessions.envelope import session_time_envelope

    segments = [{"start_time": "19:00", "duration_minutes": 60}]
    start, end = session_time_envelope(segments)
    assert start == "19:00"
    assert end == "20:00"


def test_multiple_nonoverlapping_segments_envelope_spans_all() -> None:
    """For non-overlapping, sequential segments the envelope must span from
    the earliest segment start to the latest segment end."""
    from app.sessions.envelope import session_time_envelope

    segments = [
        {"start_time": "18:00", "duration_minutes": 30},  # 18:00-18:30
        {"start_time": "18:30", "duration_minutes": 45},  # 18:30-19:15
        {"start_time": "19:15", "duration_minutes": 30},  # 19:15-19:45
    ]
    start, end = session_time_envelope(segments)
    assert start == "18:00"
    assert end == "19:45"


def test_overlapping_segments_envelope_uses_min_start_max_end() -> None:
    """Overlapping segments must still produce a correct envelope: the
    earliest start across all segments and the latest end across all
    segments, regardless of declared order."""
    from app.sessions.envelope import session_time_envelope

    segments = [
        {"start_time": "19:00", "duration_minutes": 90},  # 19:00-20:30
        {"start_time": "19:30", "duration_minutes": 30},  # 19:30-20:00 (nested)
        {"start_time": "18:45", "duration_minutes": 20},  # 18:45-19:05 (overlaps start)
    ]
    start, end = session_time_envelope(segments)
    assert start == "18:45"
    assert end == "20:30"


def test_segments_out_of_order_in_input_still_derive_correct_envelope() -> None:
    """Input order must not matter — envelope is derived from values, not
    list position."""
    from app.sessions.envelope import session_time_envelope

    segments = [
        {"start_time": "20:00", "duration_minutes": 15},  # 20:00-20:15 (latest end)
        {"start_time": "09:00", "duration_minutes": 10},  # 09:00-09:10 (earliest start)
    ]
    start, end = session_time_envelope(segments)
    assert start == "09:00"
    assert end == "20:15"
