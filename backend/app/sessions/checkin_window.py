"""Pure derivation of check-in window status from a session's envelope.

DOJO-WIDE DEFAULTS ONLY (issue #192) — the caller supplies before/after
minutes sourced from dojo settings; per-session overrides are a separate,
later slice.

This module is pure / I/O-free: no DB, no clock reads (the caller supplies
`now`), no settings lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class CheckinWindowStatus(StrEnum):
    OPEN = "open"
    TOO_EARLY = "too_early"
    CLOSED = "closed"


@dataclass(frozen=True)
class CheckinWindowResult:
    status: CheckinWindowStatus
    opens_at: datetime
    closes_at: datetime


def classify_checkin_window(
    *,
    session_start: datetime,
    session_end: datetime,
    before_minutes: int,
    after_minutes: int,
    now: datetime,
) -> CheckinWindowResult:
    """Classify `now` against the check-in window for a session.

    opens_at = session_start - before_minutes
    closes_at = session_end + after_minutes
    Boundaries are inclusive: `now` exactly at opens_at or closes_at is OPEN.
    """
    opens_at = session_start - timedelta(minutes=before_minutes)
    closes_at = session_end + timedelta(minutes=after_minutes)

    if now < opens_at:
        status = CheckinWindowStatus.TOO_EARLY
    elif now > closes_at:
        status = CheckinWindowStatus.CLOSED
    else:
        status = CheckinWindowStatus.OPEN

    return CheckinWindowResult(status=status, opens_at=opens_at, closes_at=closes_at)
