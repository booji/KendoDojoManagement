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
                        "notes": None,
                        "segments": _copy_segments(template),
                    }
                )
            current += timedelta(weeks=interval_weeks)

    return instances


def needs_rolling_extension(
    latest_date: date | None, today: date, threshold_days: int = 14
) -> bool:
    """Returns True if latest_date is None or within threshold_days of today."""
    if latest_date is None:
        return True
    return (latest_date - today).days <= threshold_days
