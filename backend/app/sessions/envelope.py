"""Pure derivation of a session's displayed time from its segments.

A session (instance or template) no longer carries its own start_time /
duration_minutes — those are derived on read from the union of its
segments:

    envelope_start = min(segment.start_time)
    envelope_end   = max(segment.start_time + segment.duration_minutes)

Segments may overlap; the envelope is simply the outer bound across all of
them, regardless of input order.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _to_minutes(hhmm: str) -> int:
    hour, minute = (int(p) for p in hhmm.split(":"))
    return hour * 60 + minute


def _to_hhmm(total_minutes: int) -> str:
    hour, minute = divmod(total_minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def session_time_envelope(segments: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (start, end) as "HH:MM" strings spanning all given segments.

    Raises ValueError if segments is empty — callers must enforce the
    "at least one segment" invariant before calling this.
    """
    if not segments:
        raise ValueError("Cannot derive a time envelope from zero segments")

    starts = [_to_minutes(s["start_time"]) for s in segments]
    ends = [_to_minutes(s["start_time"]) + s["duration_minutes"] for s in segments]

    return _to_hhmm(min(starts)), _to_hhmm(max(ends))


def envelope_bounds(
    date_str: str, start_time: str, end_time: str
) -> tuple[datetime, datetime]:
    """Turn a session's date plus envelope "HH:MM" strings into naive local
    datetimes.

    The envelope end may be "24:00" or beyond (e.g. "24:15", "25:00") when a
    segment runs to or past midnight — ``session_time_envelope`` emits the end
    as raw hours-since-midnight with no 24-hour wrap. Building each datetime as
    a timedelta offset from midnight rolls those hours into the following day
    instead of blowing up ``datetime`` / ``strptime`` (hours must be 0..23).
    """
    year, month, day = (int(p) for p in date_str.split("-"))
    midnight = datetime(year, month, day)
    return (
        midnight + timedelta(minutes=_to_minutes(start_time)),
        midnight + timedelta(minutes=_to_minutes(end_time)),
    )
