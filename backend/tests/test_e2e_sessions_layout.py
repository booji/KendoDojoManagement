"""
E2E browser tests for issue #83 — sessions list layout on desktop.

xfail stubs — these will be promoted to real assertions once the frontend
implementation is complete.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

BASE_URL = "http://localhost:5173"


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_sessions_list_horizontal_layout_on_desktop(page: Page) -> None:
    """Sessions list shows a horizontal card layout on viewport width >=768px."""
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_sessions_list_attendance_count_visible_for_admin(page: Page) -> None:
    """Admin cards show an attendance count badge on the sessions list."""
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_sessions_list_checkin_status_visible_for_member(page: Page) -> None:
    """Member cards show check-in status inline on the sessions list."""
    pytest.fail("not implemented")
