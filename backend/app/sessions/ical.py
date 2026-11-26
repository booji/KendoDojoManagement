"""Pure iCal generation — no side effects, no I/O."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.sessions.envelope import session_time_envelope

# Explicit allowlist: only these fields reach the public iCal output.
# coach_notes, notes and other admin-only fields are never included.
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

# Per-segment fields allowed into the public breakdown. title is public and
# included; the per-segment note was removed in #406, and this allow-list is
# what keeps a row written before that from reaching the feed.
_PUBLIC_SEGMENT_FIELDS = frozenset(
    {"start_time", "duration_minutes", "type_names", "title"}
)


# Session info is markdown. js-default matches the frontend's remark-gfm
# closely (tables, strikethrough) and has html=False: raw HTML in info is
# escaped as text, never passed through. Its link validation drops
# javascript: and similar URLs.
_markdown = MarkdownIt("js-default")


def _inline_text(children: list[Token]) -> str:
    parts: list[str] = []
    link_start, href = 0, ""
    for tok in children:
        if tok.type in ("text", "code_inline", "image"):
            parts.append(tok.content)
        elif tok.type in ("softbreak", "hardbreak"):
            parts.append("\n")
        elif tok.type == "link_open":
            link_start, href = len(parts), str(tok.attrGet("href") or "")
        elif tok.type == "link_close":
            label = "".join(parts[link_start:])
            if href and href not in (label, f"mailto:{label}"):
                parts.append(f" ({href})")
    return "".join(parts)


def _markdown_to_text(source: str) -> str:
    """Render markdown as readable plain text: markers dropped, list items
    bulleted or numbered, links as "text (url)"."""
    blocks: list[tuple[int, str]] = []  # (list depth, text)
    depth, prefix = 0, ""
    for tok in _markdown.parse(source):
        if tok.type in ("bullet_list_open", "ordered_list_open"):
            depth += 1
        elif tok.type in ("bullet_list_close", "ordered_list_close"):
            depth -= 1
        elif tok.type == "list_item_open":
            marker = f"{tok.info}{tok.markup}" if tok.info else "•"
            prefix = f"{'  ' * (depth - 1)}{marker} "
        elif tok.type == "inline":
            # ponytail: table cells come out one block each, readable but not
            # a grid; lay out rows if dojos start putting tables in info.
            blocks.append((depth, prefix + _inline_text(tok.children or [])))
            prefix = ""
        elif tok.type in ("fence", "code_block"):
            blocks.append((depth, tok.content.rstrip("\n")))
    text = ""
    for i, (block_depth, block) in enumerate(blocks):
        if i:
            # Items of one list sit on consecutive lines; anything else is a
            # paragraph of its own.
            text += "\n" if block_depth and blocks[i - 1][0] else "\n\n"
        text += block
    return text


def _display_name(dojo_name: str | None) -> str:
    # Same fallback as the browser tab title (frontend/src/lib/tabTitle.ts).
    return (dojo_name or "").strip() or "Kendo Dojo Management"


def feed_url_name(dojo_name: str | None) -> str:
    """The dojo name as the Calendar Feed URL's last segment (decoded).

    Thunderbird and GNOME Calendar name a subscription after that segment and
    ignore X-WR-CALNAME. "/" becomes "-" so the name stays one segment.
    frontend/src/lib/calendarFeed.ts applies the same rule.
    """
    return _display_name(dojo_name).replace("/", "-")


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


def _fold(line: str) -> str:
    """Fold a content line at 75 octets (RFC 5545 §3.1). Each continuation
    starts with a space, which counts toward its 75, and a fold never splits
    a multi-byte UTF-8 character."""
    chunks, current, size = [], "", 0
    for char in line:
        octets = len(char.encode())
        if size + octets > 75:
            chunks.append(current)
            current, size = "", 1
        current += char
        size += octets
    chunks.append(current)
    return "\r\n ".join(chunks)


def _segment_breakdown_line(segment: dict[str, Any]) -> str:
    start = segment["start_time"]
    hour, minute = (int(p) for p in start.split(":"))
    end_minutes = hour * 60 + minute + segment["duration_minutes"]
    end_hour, end_minute = divmod(end_minutes, 60)
    end = f"{end_hour:02d}:{end_minute:02d}"
    types = ", ".join(segment.get("type_names") or [])
    # " - "-joined [time-range, types, title?]. Time-range and types are always
    # present (a segment requires at least one type); title is only included
    # when present, so a bare segment never renders a dangling separator.
    # RFC 5545 escaping (applied later) handles any commas/dashes.
    parts = [f"{start}-{end}", types]
    title = segment.get("title")
    if title:
        parts.append(title)
    return " - ".join(parts)


def _build_descriptions(session: dict[str, Any]) -> tuple[str, str] | None:
    """The event description as (plain text, HTML), or None when empty: the
    check-in link, then the segment breakdown, then the session's info."""
    segments = session.get("segments") or []
    breakdown_lines = [
        _segment_breakdown_line({k: s.get(k) for k in _PUBLIC_SEGMENT_FIELDS})
        for s in segments
    ]
    info = session.get("info")
    checkin_link = session.get("checkin_link")
    if not (breakdown_lines or info or checkin_link):
        return None

    text_parts: list[str] = []
    html_parts: list[str] = []
    if checkin_link:
        text_parts.append(f"Check in: {checkin_link}")
        link = escape(checkin_link)
        html_parts.append(f'<p>Check in: <a href="{link}">{link}</a></p>')
    body = "\n".join(breakdown_lines + ([_markdown_to_text(info)] if info else []))
    if body:
        text_parts.append(body)
    if breakdown_lines:
        html_parts.append(f"<p>{'<br>'.join(map(escape, breakdown_lines))}</p>")
    if info:
        html_parts.append(_markdown.render(info))
    return "\n\n".join(text_parts), f"<html><body>{''.join(html_parts)}</body></html>"


def _event_bounds(session: dict[str, Any]) -> tuple[datetime, datetime]:
    """Return the (start, end) naive local datetimes spanning a session's
    segment envelope. These wall-clock times are interpreted in the dojo's
    timezone when a TZID is applied at output time."""
    date_str = session["date"]  # "YYYY-MM-DD"
    start_time_str, end_time_str = session_time_envelope(session.get("segments") or [])

    year, month, day = (int(p) for p in date_str.split("-"))
    start_hour, start_minute = (int(p) for p in start_time_str.split(":"))
    end_hour, end_minute = (int(p) for p in end_time_str.split(":"))
    midnight = datetime(year, month, day, 0, 0, 0)
    # end may be 24:00 (or beyond) when a segment runs to/past midnight; add as
    # an offset from midnight so hours >23 don't blow up the datetime ctor.
    start_dt = midnight + timedelta(hours=start_hour, minutes=start_minute)
    end_dt = midnight + timedelta(hours=end_hour, minutes=end_minute)
    return start_dt, end_dt


def _build_vevent(session: dict[str, Any], tz_name: str | None = None) -> str:
    uid = session["id"]
    summary = _escape_text(session.get("title", "") or "")
    start_dt, end_dt = _event_bounds(session)

    # With a dojo timezone, tag the wall-clock times with TZID so clients resolve
    # them against the VTIMEZONE definition (correct instant, DST-aware) instead
    # of treating them as floating local time.
    tzid = f";TZID={tz_name}" if tz_name else ""
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{summary}",
        f"DTSTART{tzid}:{_dt_to_ical(start_dt)}",
        f"DTEND{tzid}:{_dt_to_ical(end_dt)}",
    ]

    location = session.get("location")
    if location:
        lines.append(f"LOCATION:{_escape_text(location)}")

    descriptions = _build_descriptions(session)
    if descriptions:
        text, html = descriptions
        lines.append(f"DESCRIPTION:{_escape_text(text)}")
        # Plain-text DESCRIPTION is what Apple and Google show; Outlook
        # renders the HTML alternative.
        lines.append(f"X-ALT-DESC;FMTTYPE=text/html:{_escape_text(html)}")

    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def _fmt_offset(off: timedelta) -> str:
    """Format a UTC offset as RFC 5545 ±HHMM."""
    secs = int(off.total_seconds())
    sign = "-" if secs < 0 else "+"
    secs = abs(secs)
    return f"{sign}{secs // 3600:02d}{(secs % 3600) // 60:02d}"


def _find_transitions(
    tz: ZoneInfo, start_utc: datetime, end_utc: datetime
) -> list[datetime]:
    """Return the UTC instants in (start_utc, end_utc] at which the zone's
    offset changes, located by a daily coarse scan refined to the second."""
    transitions: list[datetime] = []
    step = timedelta(days=1)
    cur = start_utc
    cur_off = cur.astimezone(tz).utcoffset()
    while cur < end_utc:
        nxt = min(cur + step, end_utc)
        nxt_off = nxt.astimezone(tz).utcoffset()
        if nxt_off != cur_off:
            lo, hi = cur, nxt
            while hi - lo > timedelta(seconds=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(tz).utcoffset() == cur_off:
                    lo = mid
                else:
                    hi = mid
            transitions.append(hi)
            cur_off = nxt_off
        cur = nxt
    return transitions


def _observance(tz: ZoneInfo, instant_utc: datetime) -> str:
    """Render one STANDARD/DAYLIGHT sub-component for the offset change at the
    given UTC instant. DTSTART is the local onset expressed in the *previous*
    offset (TZOFFSETFROM), per RFC 5545 §3.6.5."""
    before = (instant_utc - timedelta(seconds=1)).astimezone(tz)
    after = instant_utc.astimezone(tz)
    off_from = before.utcoffset() or timedelta()
    off_to = after.utcoffset() or timedelta()
    kind = "DAYLIGHT" if after.dst() else "STANDARD"
    onset_local = (instant_utc + off_from).strftime("%Y%m%dT%H%M%S")
    return "\r\n".join(
        [
            f"BEGIN:{kind}",
            f"DTSTART:{onset_local}",
            f"TZOFFSETFROM:{_fmt_offset(off_from)}",
            f"TZOFFSETTO:{_fmt_offset(off_to)}",
            f"TZNAME:{after.tzname()}",
            f"END:{kind}",
        ]
    )


def _build_vtimezone(tz_name: str, moments: list[datetime]) -> str:
    """Build a VTIMEZONE defining tz_name across the span of the given naive
    local datetimes: the observance in force at the earliest moment plus every
    DST transition up to the latest, so each event resolves to the right offset."""
    tz = ZoneInfo(tz_name)
    utc_moments = [m.replace(tzinfo=tz).astimezone(UTC) for m in moments]
    earliest, latest = min(utc_moments), max(utc_moments)

    # Governing observance: the last transition at or before the earliest event
    # (search back a little over a year to be sure to catch it).
    prior = _find_transitions(tz, earliest - timedelta(days=400), earliest)
    instants = ([prior[-1]] if prior else []) + _find_transitions(tz, earliest, latest)

    lines = ["BEGIN:VTIMEZONE", f"TZID:{tz_name}"]
    if instants:
        lines.extend(_observance(tz, i) for i in instants)
    else:
        # Fixed-offset zone (e.g. UTC): one STANDARD block still defines the TZID.
        off = earliest.astimezone(tz).utcoffset() or timedelta()
        lines.append(
            "\r\n".join(
                [
                    "BEGIN:STANDARD",
                    "DTSTART:19700101T000000",
                    f"TZOFFSETFROM:{_fmt_offset(off)}",
                    f"TZOFFSETTO:{_fmt_offset(off)}",
                    f"TZNAME:{earliest.astimezone(tz).tzname()}",
                    "END:STANDARD",
                ]
            )
        )
    lines.append("END:VTIMEZONE")
    return "\r\n".join(lines)


def build_ical(
    sessions: list[dict[str, Any]],
    tz_name: str | None = None,
    calendar_name: str | None = None,
) -> str:
    """Return a valid RFC 5545 iCal string for the given session dicts.

    Cancelled sessions are excluded. Only _PUBLIC_FIELDS (and, within each
    segment, only _PUBLIC_SEGMENT_FIELDS) are passed to the event builder —
    admin-only fields (session-level coach_notes, notes, etc.) are stripped
    here regardless of what the caller passes in.

    Exactly one VEVENT is produced per session, with DTSTART/DTEND derived
    from the min-start/max-end envelope across all of that session's
    segments, and DESCRIPTION listing each segment's time range and types
    followed by the session's public info text.

    When tz_name (an IANA zone) is given, each event's wall-clock times are
    tagged with TZID and a matching VTIMEZONE component is emitted so clients
    resolve them to the correct, DST-aware instant. Without it, times are
    floating (legacy behaviour).

    calendar_name (the dojo name) is what calendar apps show the feed as.
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
    name = _escape_text(_display_name(calendar_name))

    header = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//KendoDojoManagement//EN",
            "CALSCALE:GREGORIAN",
            # NAME is RFC 7986; X-WR-CALNAME is the older property most
            # calendar apps still read. Without either they show the URL.
            f"X-WR-CALNAME:{name}",
            f"NAME:{name}",
        ]
    )

    events = "\r\n".join(_build_vevent(s, tz_name) for s in non_cancelled)

    parts = [header]
    # VTIMEZONE must precede the events that reference its TZID.
    if tz_name and non_cancelled:
        moments = [dt for s in non_cancelled for dt in _event_bounds(s)]
        parts.append(_build_vtimezone(tz_name, moments))
    if events:
        parts.append(events)
    parts.append("END:VCALENDAR")

    lines = "\r\n".join(parts).split("\r\n")
    return "\r\n".join(map(_fold, lines)) + "\r\n"
