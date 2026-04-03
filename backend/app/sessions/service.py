from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def generate_instances(
    template: dict[str, Any],
    horizon: date,
) -> list[dict[str, Any]]:
    """Pure function — generates session instances for each matching weekday
    between the template's start_date and horizon (inclusive)."""
    start = date.fromisoformat(template["start_date"])
    target_dow = template["day_of_week"]  # 0=Monday … 6=Sunday

    # Advance start to the first matching weekday on or after start_date
    days_ahead = (target_dow - start.weekday()) % 7
    current = start + timedelta(days=days_ahead)

    instances: list[dict[str, Any]] = []
    while current <= horizon:
        instances.append(
            {
                "session_type_id": template["session_type_id"],
                "date": current.isoformat(),
                "start_time": template["start_time"],
                "duration_minutes": template["duration_minutes"],
                "template_id": template["id"],
                "notes": None,
            }
        )
        current += timedelta(weeks=1)

    return instances
