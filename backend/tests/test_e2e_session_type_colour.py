"""
E2E browser test stubs for issue #76 — admin-configurable colour per session type.

One xfail stub per acceptance criterion. Replace with real Playwright assertions
after implementation is complete (QA phase).

Acceptance criteria:
  1. Admin can set a colour on any session type from the admin settings page
  2. Colour is persisted and returned on GET /session-types
  3. Calendar chips use the admin-chosen colour; fall back to auto-palette if no colour set
  4. Cancelled sessions remain fully grey regardless of type colour
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

BASE_URL = "http://localhost:5173"


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_admin_can_set_colour_on_session_type(page: Page) -> None:
    """AC1: Admin can set a colour on any session type from the admin settings page."""
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_session_type_colour_persisted_and_returned(page: Page) -> None:
    """AC2: Colour is persisted and returned on GET /session-types."""
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_calendar_chips_use_admin_chosen_colour_with_auto_palette_fallback(
    page: Page,
) -> None:
    """AC3: Calendar chips use the admin-chosen colour; fall back to auto-palette if no colour set."""
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_cancelled_sessions_remain_grey_regardless_of_type_colour(page: Page) -> None:
    """AC4: Cancelled sessions remain fully grey regardless of type colour."""
    pytest.fail("not implemented")
