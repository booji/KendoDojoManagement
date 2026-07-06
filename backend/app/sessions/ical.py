"""Pure iCal generation — no side effects, no I/O."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.sessions.envelope import session_time_envelope

# Explicit allowlist: only these fields reach the public iCal output.
# coach_notes, checkin_url, notes and other admin-only fields are never included.
_PUBLIC_FIELDS = frozenset(
    {
        "id",
        "title",
        "date",
        "location",
        "info",
        "cancelled",
        "segments",
        "checkin_link",
    }
)

# Per-segment fields allowed into the public breakdown. title and note are
# public and included.
_PUBLIC_SEGMENT_FIELDS = frozenset(
    {"start_time", "duration_minutes", "type_names", "title", "note"}
)


def _dt_to_ical(dt: datetime) -> str:
    """Format a naive datetime as YYYYMMDDTHHMMSS (local / floating time)."""
    return dt.strftime("%Y%m%dT%H%M%S")


def _escape_text(value: str) -> str:
    # RFC 5545 §3.3.11: escape backslashes, semicolons, and commas; fold
    # newlines. Commas in our comma-joined segment type lists are escaped to
    # "\," — calendar clients unescape this back to a literal comma for
    # display, so "Jigeki, Kata Practice" still renders correctly.
    value = value.replace("\\", "\\\\")
    value = value.replace(";", "\\;").replace(",", "\\,")
    value = value.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return value


def _segment_breakdown_line(segment: dict[str, Any]) -> str:
    start = segment["start_time"]
    hour, minute = (int(p) for p in start.split(":"))
    end_minutes = hour * 60 + minute + segment["duration_minutes"]
    end_hour, end_minute = divmod(end_minutes, 60)
    end = f"{end_hour:02d}:{end_minute:02d}"
    types = ", ".join(segment.get("type_names") or [])
    # " - "-joined [time-range, types, title?, note?]. Time-range and types are
    # always present (a segment requires at least one type); title and note are
    # only included when present, so a bare segment never renders a dangling
    # separator. RFC 5545 escaping (applied later) handles any commas/dashes.
    parts = [f"{start}-{end}", types]
    title = segment.get("title")
    if title:
        parts.append(title)
    note = segment.get("note")
    if note:
        parts.append(note)
    return " - ".join(parts)


def _build_description(session: dict[str, Any]) -> str | None:
    segments = session.get("segments") or []
    breakdown_lines = [
        _segment_breakdown_line({k: s.get(k) for k in _PUBLIC_SEGMENT_FIELDS})
        for s in segments
    ]
    info = session.get("info")
    parts = list(breakdown_lines)
    if info:
        parts.append(info)
    body = "\n".join(parts)

    checkin_link = session.get("checkin_link")
    if checkin_link:
        checkin_line = f"Check in: {checkin_link}"
        return f"{checkin_line}\n\n{body}" if body else checkin_line
    if not parts:
        return None
    return body


def _build_vevent(session: dict[str, Any]) -> str:
    uid = session["id"]
    summary = _escape_text(session.get("title", "") or "")
    date_str = session["date"]  # "YYYY-MM-DD"
    segments = session.get("segments") or []

    start_time_str, end_time_str = session_time_envelope(segments)

    year, month, day = (int(p) for p in date_str.split("-"))
    start_hour, start_minute = (int(p) for p in start_time_str.split(":"))
    end_hour, end_minute = (int(p) for p in end_time_str.split(":"))
    start_dt = datetime(year, month, day, start_hour, start_minute, 0)
    end_dt = datetime(year, month, day, end_hour, end_minute, 0)
    if end_dt < start_dt:
        # Envelope end wrapped past midnight — shouldn't normally happen for
        # same-day segments, but guard against a degenerate ordering.
        end_dt += timedelta(days=1)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{summary}",
        f"DTSTART:{_dt_to_ical(start_dt)}",
        f"DTEND:{_dt_to_ical(end_dt)}",
    ]

    location = session.get("location")
    if location:
        lines.append(f"LOCATION:{_escape_text(location)}")

    description = _build_description(session)
    if description:
        lines.append(f"DESCRIPTION:{_escape_text(description)}")

    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def build_ical(sessions: list[dict[str, Any]]) -> str:
    """Return a valid RFC 5545 iCal string for the given session dicts.

    Cancelled sessions are excluded. Only _PUBLIC_FIELDS (and, within each
    segment, only _PUBLIC_SEGMENT_FIELDS) are passed to the event builder —
    admin-only fields (coach_notes at session or segment level, checkin_url,
    notes, etc.) are stripped here regardless of what the caller passes in.

    Exactly one VEVENT is produced per session, with DTSTART/DTEND derived
    from the min-start/max-end envelope across all of that session's
    segments, and DESCRIPTION listing each segment's time range and types
    followed by the session's public info text.
    """
    public = []
    for s in sessions:
        segments = [
            {k: seg.get(k) for k in _PUBLIC_SEGMENT_FIELDS}
            for seg in (s.get("segments") or [])
        ]
        entry = {k: s.get(k) for k in _PUBLIC_FIELDS if k != "segments"}
        entry["segments"] = segments
        public.append(entry)

    non_cancelled = [s for s in public if not s.get("cancelled", False)]

    header = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//KendoDojoManagement//EN",
            "CALSCALE:GREGORIAN",
        ]
    )

    events = "\r\n".join(_build_vevent(s) for s in non_cancelled)

    parts = [header]
    if events:
        parts.append(events)
    parts.append("END:VCALENDAR")

    return "\r\n".join(parts) + "\r\n"
