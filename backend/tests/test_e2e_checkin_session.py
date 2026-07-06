"""
Playwright browser test stubs for issue #191 — tokenless check-in link in
the iCal feed, served by a new /checkin/session/:id frontend page.

This slice has NO time-window enforcement; the page simply drives
POST /sessions/{id}/checkin and renders the resulting state. These stubs
are RED-phase placeholders per the tdd skill: xfail(strict=True) with a
pytest.fail body. They must be promoted to real Playwright assertions once
the page and route exist (see frontend/src/pages/SessionCheckinPage.tsx and
the /checkin/session/:id route wiring in App.tsx).

One stub per relevant acceptance criterion from the issue:
  - success state
  - already-checked-in (409) state
  - cancelled (409) state
  - not-found (404) state
  - unauthenticated -> redirected to log in and back
"""

from __future__ import annotations

import pytest

BASE_URL = "http://localhost:5173"


@pytest.mark.xfail(
    strict=True,
    reason="SessionCheckinPage / /checkin/session/:id route not implemented yet.",
)
def test_checkin_session_success_state() -> None:
    """Visiting /checkin/session/{id} for a valid, non-cancelled, upcoming
    session as a logged-in member checks the member in and shows a success
    message."""
    pytest.fail("not implemented")


@pytest.mark.xfail(
    strict=True,
    reason="SessionCheckinPage / /checkin/session/:id route not implemented yet.",
)
def test_checkin_session_already_checked_in_state() -> None:
    """Visiting /checkin/session/{id} a second time for the same session
    shows an 'already checked in' message (409, distinguished from
    cancelled only by the response detail string)."""
    pytest.fail("not implemented")


@pytest.mark.xfail(
    strict=True,
    reason="SessionCheckinPage / /checkin/session/:id route not implemented yet.",
)
def test_checkin_session_cancelled_state() -> None:
    """Visiting /checkin/session/{id} for a cancelled session shows a
    cancelled message (409, distinguished only by the response detail
    string)."""
    pytest.fail("not implemented")


@pytest.mark.xfail(
    strict=True,
    reason="SessionCheckinPage / /checkin/session/:id route not implemented yet.",
)
def test_checkin_session_not_found_state() -> None:
    """Visiting /checkin/session/{id} for a non-existent session id shows a
    not-found message (404)."""
    pytest.fail("not implemented")


@pytest.mark.xfail(
    strict=True,
    reason="SessionCheckinPage / /checkin/session/:id route not implemented yet.",
)
def test_checkin_session_unauthenticated_redirects_to_login_and_back() -> None:
    """An unauthenticated visitor to /checkin/session/{id} is routed to
    /login, and after logging in is returned to complete the check-in."""
    pytest.fail("not implemented")
