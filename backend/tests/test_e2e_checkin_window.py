"""
Playwright browser test stubs for issue #192 — check-in window enforcement
with dojo-wide defaults.

Scope: DOJO-WIDE DEFAULTS ONLY. Per-session override columns are a separate,
later slice and are out of scope here.

These are RED-phase placeholders per the tdd skill's xfail lifecycle:
each is marked xfail(strict=True) and must be promoted to a real Playwright
assertion (and have the xfail marker removed) once the corresponding UI is
implemented. A stub left as xfail forever provides no protection.

One stub per relevant acceptance criterion:
  7. Check-in page renders a too-early state ("opens at …").
  7. Check-in page renders a closed state ("closed at …").
  3. Admin settings page has a "Check-in window" card with the two default
     minute inputs.
  3. Admin settings "Check-in window" card validates non-negative integers
     <= 1440.
"""

import pytest
from playwright.sync_api import Page

BASE_URL = "http://localhost:5173"


# ── AC7 — Too-early state on the check-in page ──────────────────────────────


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_checkin_page_shows_too_early_state(page: Page) -> None:
    pytest.fail("not implemented")


# ── AC7 — Closed state on the check-in page ─────────────────────────────────


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_checkin_page_shows_closed_state(page: Page) -> None:
    pytest.fail("not implemented")


# ── AC3 — Admin settings "Check-in window" card with two default inputs ────


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_admin_settings_shows_checkin_window_card_with_two_inputs(page: Page) -> None:
    pytest.fail("not implemented")


# ── AC3 — Admin settings "Check-in window" validation (0-1440 integer) ─────


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_admin_settings_checkin_window_rejects_invalid_minutes(page: Page) -> None:
    pytest.fail("not implemented")
