"""
Playwright browser test stubs for issue #52 — iCal feed endpoint + checkin_url.

Issue #52 is backend-only: it adds GET /sessions/ical and persists checkin_url
on SessionInstance. There is no frontend UI for iCal subscription or for
displaying the checkin_url field. All acceptance criteria are verified in
backend/tests/test_ical.py (unit/integration level).

These stubs remain xfail because there is no frontend surface to drive with
Playwright. They should be promoted when a UI is added (e.g., a "Subscribe to
calendar" button or a session detail page that renders the check-in URL).
"""

from __future__ import annotations

import pytest

BASE_URL = "http://localhost:5173"


# ---------------------------------------------------------------------------
# AC1 — GET /sessions/ical returns 200 text/calendar without authentication
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "No frontend UI for iCal subscription. "
        "Covered at API level by test_ical.py::test_ical_endpoint_returns_200_no_auth. "
        "Promote when a 'Subscribe to calendar' link/button appears in the UI."
    ),
)
def test_ical_feed_accessible_without_login() -> None:
    """The iCal feed URL is reachable by an unauthenticated browser/client and
    returns a valid calendar response."""
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC2 — Feed includes VEVENT blocks with title, date/time, duration, location, info
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "No frontend UI renders the iCal feed content. "
        "Covered at API level by test_ical.py (test_ical_feed_includes_vevent_with_summary, "
        "test_ical_feed_includes_dtstart_and_dtend, test_ical_feed_includes_location, etc.). "
        "Promote when a UI surfaces session details from the iCal feed."
    ),
)
def test_ical_feed_contains_session_details() -> None:
    """Downloading the iCal feed shows session titles, dates, durations,
    locations, and info in VEVENT blocks."""
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC3 — coach_notes is never included in iCal output
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "No frontend surface for iCal content inspection. "
        "Covered at API level by test_ical.py::test_ical_feed_never_includes_coach_notes. "
        "Promote if a UI ever exposes iCal preview or coach notes visibility toggles."
    ),
)
def test_ical_feed_does_not_expose_coach_notes() -> None:
    """The iCal feed content does not contain coach notes even when they are
    stored on a session instance."""
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC4 — UIDs are stable (UUID of the session instance)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "No frontend UI displays or depends on VEVENT UIDs. "
        "Covered at API level by test_ical.py::test_ical_vevent_uid_equals_instance_uuid "
        "and test_ical_vevent_uid_stable_across_requests. "
        "Promote when UID stability is surfaced through a UI feature."
    ),
)
def test_ical_vevent_uid_is_stable() -> None:
    """Requesting the iCal feed twice produces identical UID values for each
    session instance VEVENT."""
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC5 — generate_checkin_token persists the URL to SessionInstance.checkin_url
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "No frontend UI displays checkin_url on session detail pages. "
        "Covered at API level by test_ical.py::test_generate_checkin_token_persists_checkin_url. "
        "Promote when a session detail view renders the persisted check-in URL."
    ),
)
def test_checkin_url_visible_after_token_generation() -> None:
    """After an admin generates a check-in token, the session detail view
    (or API response) shows the persisted checkin_url for that session."""
    pytest.fail("not implemented")
