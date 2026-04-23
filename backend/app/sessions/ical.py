"""Pure iCal generation — no side effects, no I/O."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# Explicit allowlist: only these fields reach the public iCal output.
# coach_notes, checkin_url, notes and other admin-only fields are never included.
_PUBLIC_FIELDS = frozenset(
    {
        "id",
        "title",
        "date",
        "start_time",
        "duration_minutes",
        "location",
        "info",
        "cancelled",
    }
)


def _dt_to_ical(dt: datetime) -> str:
    """Format a naive datetime as YYYYMMDDTHHMMSS (local / floating time)."""
    return dt.strftime("%Y%m%dT%H%M%S")


def _escape_text(value: str) -> str:
    # RFC 5545 §3.3.11: escape backslashes, semicolons, commas; fold newlines.
    value = value.replace("\\", "\\\\")
    value = value.replace(";", "\\;").replace(",", "\\,")
    value = value.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return value


def _build_vevent(session: dict[str, Any]) -> str:
    uid = session["id"]
    summary = _escape_text(session.get("title", "") or "")
    date_str = session["date"]  # "YYYY-MM-DD"
    start_time_str = session.get("start_time", "00:00")  # "HH:MM"
    duration_minutes = session.get("duration_minutes", 60)

    # Parse start datetime
    hour, minute = (int(p) for p in start_time_str.split(":"))
    year, month, day = (int(p) for p in date_str.split("-"))
    start_dt = datetime(year, month, day, hour, minute, 0)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

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

    info = session.get("info")
    if info:
        lines.append(f"DESCRIPTION:{_escape_text(info)}")

    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def build_ical(sessions: list[dict[str, Any]]) -> str:
    """Return a valid RFC 5545 iCal string for the given session dicts.

    Cancelled sessions are excluded. Only _PUBLIC_FIELDS are passed to the
    event builder — admin-only fields (coach_notes, checkin_url, notes, etc.)
    are stripped here regardless of what the caller passes in.
    """
    public = [{k: s.get(k) for k in _PUBLIC_FIELDS} for s in sessions]
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
