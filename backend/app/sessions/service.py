from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any


def _copy_segments(template: dict[str, Any]) -> list[dict[str, Any]]:
    """Deep-copy a template's segments (and their type links) so that each
    generated instance gets independently editable segment data — no shared
    rows between the template and its generated instances, or between
    sibling instances."""
    return copy.deepcopy(template.get("segments") or [])


def generate_instances(
    template: dict[str, Any],
    horizon: date,
    existing_dates: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Pure function — generates session instances for each matching weekday
    between the template's start_date and horizon (inclusive).

    Supports both:
    - New style: recurrence_days (list of weekday ints) + interval_weeks
    - Old style: day_of_week (single int) + weekly recurrence (backwards compat)

    Dates already in existing_dates (as ISO strings) are skipped.

    Each generated instance is given its own deep copy of the template's
    segments so subsequent edits to one instance never affect another.
    """
    start = date.fromisoformat(template["start_date"])
    existing = existing_dates or set()

    recurrence_days: list[int] = template.get("recurrence_days") or []
    interval_weeks: int = max(1, template.get("interval_weeks") or 1)

    # Fall back to old-style day_of_week if recurrence_days is empty
    if not recurrence_days:
        dow = template.get("day_of_week")
        if dow is not None:
            recurrence_days = [dow]
        else:
            return []

    instances: list[dict[str, Any]] = []

    for target_dow in recurrence_days:
        days_ahead = (target_dow - start.weekday()) % 7
        current = start + timedelta(days=days_ahead)
        while current <= horizon:
            iso = current.isoformat()
            if iso not in existing:
                instances.append(
                    {
                        "title": template["title"],
                        "date": iso,
                        "template_id": template["id"],
                        "location": template.get("location"),
                        "info": template.get("info"),
                        "coach_notes": template.get("coach_notes"),
                        "segments": _copy_segments(template),
                    }
                )
            current += timedelta(weeks=interval_weeks)

    return instances


# A recurring template must be bounded — six months is the cap applied both
# to the initial start_date..end_date range and to any later extension.
TEMPLATE_MAX_HORIZON_MONTHS = 6

_DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def add_months(d: date, months: int) -> date:
    """Add calendar months to a date, clamping the day if the target month is
    shorter (e.g. 31 Jan + 1 month -> 28/29 Feb)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    max_day = 29 if month == 2 and is_leap else _DAYS_IN_MONTH[month - 1]
    return date(year, month, min(d.day, max_day))


def covered_dates(template: dict[str, Any]) -> set[str]:
    """The full set of ISO date strings a template's recurrence covers across
    its start_date..end_date range — the source of truth for delta
    regeneration (add newly-covered dates, remove no-longer-covered ones)."""
    horizon = date.fromisoformat(template["end_date"])
    return {inst["date"] for inst in generate_instances(template, horizon)}
