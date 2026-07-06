"""
Unit tests for issue #192 — pure, I/O-free check-in window classification.

Scope: DOJO-WIDE DEFAULTS ONLY. Per-session override columns are a separate,
later slice and are explicitly out of scope here.

Interface under test (does not exist yet — app/sessions/checkin_window.py):

    from app.sessions.checkin_window import (
        CheckinWindowStatus,
        CheckinWindowResult,
        classify_checkin_window,
    )

    class CheckinWindowStatus(str, Enum):
        OPEN = "open"
        TOO_EARLY = "too_early"
        CLOSED = "closed"

    @dataclass(frozen=True)
    class CheckinWindowResult:
        status: CheckinWindowStatus
        opens_at: datetime   # session_start - before_minutes
        closes_at: datetime  # session_end + after_minutes

    def classify_checkin_window(
        *,
        session_start: datetime,   # naive local wall-clock datetime
        session_end: datetime,     # naive local wall-clock datetime
        before_minutes: int,
        after_minutes: int,
        now: datetime,             # naive local wall-clock datetime
    ) -> CheckinWindowResult: ...

This module must be pure / I/O-free: no DB, no clock reads (the caller
supplies `now`), no settings lookups — those are the endpoint's job.
"""

from __future__ import annotations

from datetime import datetime, timedelta

SESSION_START = datetime(2026, 7, 6, 19, 0)  # 19:00
SESSION_END = datetime(2026, 7, 6, 20, 0)  # 20:00
BEFORE_MINUTES = 60
AFTER_MINUTES = 120


def _classify(now: datetime):
    from app.sessions.checkin_window import classify_checkin_window

    return classify_checkin_window(
        session_start=SESSION_START,
        session_end=SESSION_END,
        before_minutes=BEFORE_MINUTES,
        after_minutes=AFTER_MINUTES,
        now=now,
    )


def test_returned_boundaries_match_before_and_after_minutes() -> None:
    """opens_at = session_start - before_minutes; closes_at = session_end + after_minutes."""
    result = _classify(now=SESSION_START)

    assert result.opens_at == SESSION_START - timedelta(minutes=BEFORE_MINUTES)
    assert result.closes_at == SESSION_END + timedelta(minutes=AFTER_MINUTES)


def test_too_early_just_before_open_boundary() -> None:
    """One minute before the open boundary must classify as TOO_EARLY."""
    from app.sessions.checkin_window import CheckinWindowStatus

    open_boundary = SESSION_START - timedelta(minutes=BEFORE_MINUTES)
    result = _classify(now=open_boundary - timedelta(minutes=1))

    assert result.status == CheckinWindowStatus.TOO_EARLY


def test_open_exactly_at_open_boundary() -> None:
    """`now` exactly equal to the open boundary must classify as OPEN (inclusive)."""
    from app.sessions.checkin_window import CheckinWindowStatus

    open_boundary = SESSION_START - timedelta(minutes=BEFORE_MINUTES)
    result = _classify(now=open_boundary)

    assert result.status == CheckinWindowStatus.OPEN


def test_open_within_window() -> None:
    """`now` comfortably inside the window (at session start) must be OPEN."""
    from app.sessions.checkin_window import CheckinWindowStatus

    result = _classify(now=SESSION_START)

    assert result.status == CheckinWindowStatus.OPEN


def test_open_exactly_at_close_boundary() -> None:
    """`now` exactly equal to the close boundary must classify as OPEN (inclusive)."""
    from app.sessions.checkin_window import CheckinWindowStatus

    close_boundary = SESSION_END + timedelta(minutes=AFTER_MINUTES)
    result = _classify(now=close_boundary)

    assert result.status == CheckinWindowStatus.OPEN


def test_closed_just_after_close_boundary() -> None:
    """One minute after the close boundary must classify as CLOSED."""
    from app.sessions.checkin_window import CheckinWindowStatus

    close_boundary = SESSION_END + timedelta(minutes=AFTER_MINUTES)
    result = _classify(now=close_boundary + timedelta(minutes=1))

    assert result.status == CheckinWindowStatus.CLOSED


def test_close_boundary_is_anchored_to_session_end_not_start() -> None:
    """Using a session with a long duration, the close boundary must be
    computed from session_end (not session_start) plus after_minutes —
    proving the anchor point, not just the arithmetic."""
    from app.sessions.checkin_window import classify_checkin_window

    long_start = datetime(2026, 7, 6, 9, 0)
    long_end = datetime(2026, 7, 6, 17, 0)  # 8-hour session

    result = classify_checkin_window(
        session_start=long_start,
        session_end=long_end,
        before_minutes=BEFORE_MINUTES,
        after_minutes=AFTER_MINUTES,
        now=long_end,
    )

    # If closes_at were wrongly anchored to session_start, this would be
    # long_start + 120min = 11:00, long before `now` (17:00) — CLOSED.
    assert result.closes_at == long_end + timedelta(minutes=AFTER_MINUTES)
    assert result.status == "open"


def test_before_and_after_minutes_can_be_zero() -> None:
    """Zero-minute windows collapse the open boundary to session_start and
    the close boundary to session_end — an edge case a dojo admin might
    legitimately configure."""
    from app.sessions.checkin_window import classify_checkin_window

    result = classify_checkin_window(
        session_start=SESSION_START,
        session_end=SESSION_END,
        before_minutes=0,
        after_minutes=0,
        now=SESSION_START,
    )

    assert result.opens_at == SESSION_START
    assert result.closes_at == SESSION_END
    assert result.status == "open"
